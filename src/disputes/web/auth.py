"""R-18 authentication and authorisation for the web surfaces. OWNER: web / hardening.

- Passwords: stdlib `hashlib.scrypt` (no new dependency). Stored as
  "scrypt$<n>$<r>$<p>$<salt_hex>$<hash_hex>"; verification is constant-time. Invited users who
  have not set a password carry an unusable marker ("!invite"), which never verifies.
- MFA: TOTP (RFC 6238) via `pyotp`, ±1 step, compared in constant time, and a code (30 s step)
  is accepted at most once per user (replay protection, `users.totp_last_step`).
- Sessions: server-side rows in `web_sessions` keyed by sha256(random token); the cookie carries
  only the token. Stages: MFA_PENDING (after the password, 5 min) and ACTIVE (after TOTP).
  A new token is issued at the password step and again after MFA (no fixation). Idle timeout
  `Config.session_idle_timeout_min`, absolute lifetime `SESSION_ABSOLUTE_HOURS`. Logout,
  admin revoke, deactivation and sign-in reset revoke rows; every request re-checks the row.
- Rate limiting and lockout (`auth_attempts`, Postgres, so it holds across web tasks): per
  account (keyed by sha256(lower(email)), whether or not the account exists, so lockout does not
  reveal which emails exist) and per source address. The account check, the password/TOTP check
  and the attempt record run under a per-account advisory lock.
- Client address: the socket peer, unless `DISPUTES_TRUSTED_PROXY_HOPS` > 0, in which case the
  address that many hops from the right of X-Forwarded-For (what a load balancer appends).
- Roles are checked on the server (`tenant_ids_for`, `staff_can_access_tenant`).

`cli seed-demo` (platform-core) looks up `hash_password` and `new_totp_secret` by name.
"""
from __future__ import annotations

import hashlib
import hmac
import ipaddress
import os
import re
import secrets
import time
from dataclasses import dataclass

import pyotp

from disputes.domain import Role

# scrypt parameters: n=2**14, r=8, p=1 (~16 MiB, ~50 ms). Stored with the hash so they can rise later.
_SCRYPT_N, _SCRYPT_R, _SCRYPT_P, _DKLEN = 2 ** 14, 8, 1, 32

STAFF_ROLES = frozenset({Role.SPECIALIST, Role.SUPERVISOR, Role.ADMIN, Role.AUDITOR})
ACTING_ROLES = frozenset({Role.SPECIALIST, Role.SUPERVISOR, Role.ADMIN})   # may change cases
SESSION_COOKIE = "disputes_session"
SECURE_SESSION_COOKIE = "__Host-disputes_session"     # used when cookies are Secure (no Domain, Path=/)
PENDING_COOKIE = "disputes_mfa_pending"
PENDING_MAX_AGE_S = 300
UNUSABLE_PASSWORD = "!invite"

# Policy constants. Contract request (notes): move these into config.Config so ADMIN can change them.
SESSION_ABSOLUTE_HOURS = 12
MAX_ACCOUNT_FAILURES = 5          # password or TOTP failures per account in the window -> locked
MAX_IP_FAILURES = 30              # failures per source address in the window -> throttled
FAILURE_WINDOW_MIN = 15
MAX_MFA_FAILURES_PER_PENDING = 5  # a pending (password-ok) session dies after this many bad codes
INVITE_TTL_HOURS = 72
MIN_PASSWORD_LEN = 12
MAX_PASSWORD_LEN = 256
# Passwords that are public in this repo or trivially guessed. Refused when setting a password in
# DISPUTES_ENV=demo (and the seeded one is refused at login in demo; see authenticate_password).
SEEDED_DEMO_PASSWORDS = frozenset({"synthetic-demo-pass"})
_COMMON = frozenset({"password1234", "passwordpassword", "123456789012", "qwertyuiopas", "letmein12345",
                     "changeme1234", "welcome12345", "administrator"})

GENERIC_LOGIN_ERROR = "Email or password is incorrect."
LOCKED_ERROR = ("Too many sign-in attempts. Wait 15 minutes and try again, or ask an admin to unlock "
                "your account.")


# ---------------------------------------------------------------- hashing helpers
def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def account_key(email: str) -> str:
    return hashlib.sha256(("email:" + (email or "").strip().lower()).encode("utf-8")).hexdigest()


# ---------------------------------------------------------------- passwords
def hash_password(pw: str) -> str:
    if not pw:
        raise ValueError("empty password")
    salt = os.urandom(16)
    dk = hashlib.scrypt(pw.encode("utf-8"), salt=salt, n=_SCRYPT_N, r=_SCRYPT_R, p=_SCRYPT_P, dklen=_DKLEN)
    return f"scrypt${_SCRYPT_N}${_SCRYPT_R}${_SCRYPT_P}${salt.hex()}${dk.hex()}"


def verify_password(pw: str, stored: str) -> bool:
    try:
        algo, n, r, p, salt_hex, hash_hex = stored.split("$")
        if algo != "scrypt" or len(pw or "") > MAX_PASSWORD_LEN:
            return False
        expected = bytes.fromhex(hash_hex)
        dk = hashlib.scrypt((pw or "").encode("utf-8"), salt=bytes.fromhex(salt_hex), n=int(n), r=int(r),
                            p=int(p), dklen=len(expected))
    except (ValueError, AttributeError):
        return False
    return hmac.compare_digest(dk, expected)


def environment() -> str:
    return os.environ.get("DISPUTES_ENV", "dev")


def password_policy_errors(pw: str, *, email: str = "", env: str | None = None) -> list[str]:
    """Empty list = acceptable. Length, not the email, not a common or seeded password; in
    DISPUTES_ENV=demo the seeded demo password (and DISPUTES_DEMO_PASSWORD) is refused."""
    env = env or environment()
    pw = pw or ""
    errs = []
    if len(pw) < MIN_PASSWORD_LEN:
        errs.append(f"Use at least {MIN_PASSWORD_LEN} characters.")
    if len(pw) > MAX_PASSWORD_LEN:
        errs.append(f"Use at most {MAX_PASSWORD_LEN} characters.")
    low = pw.strip().lower()
    if email and low in {email.strip().lower(), email.strip().lower().split("@")[0]}:
        errs.append("Do not use your email address as the password.")
    if low in _COMMON or len(set(pw)) < 4:
        errs.append("That password is too easy to guess.")
    seeded = set(SEEDED_DEMO_PASSWORDS)
    if os.environ.get("DISPUTES_DEMO_PASSWORD"):
        seeded.add(os.environ["DISPUTES_DEMO_PASSWORD"])
    if env == "demo" and pw in seeded:
        errs.append("That password is published with the demo data and cannot be used here.")
    return errs


# ---------------------------------------------------------------- TOTP
def new_totp_secret() -> str:
    return pyotp.random_base32()


def totp_match_step(secret: str | None, code: str | None, *, at: float | None = None) -> int | None:
    """The 30 s step the code matches (current step ±1), or None. Constant-time comparison."""
    if not secret or not code:
        return None
    code = str(code).strip().replace(" ", "")
    if not (code.isdigit() and len(code) == 6):
        return None
    t = time.time() if at is None else at
    totp = pyotp.TOTP(secret)
    step = int(t // totp.interval)
    hit = None
    for off in (-1, 0, 1):            # check all three, so timing does not reveal which matched
        if hmac.compare_digest(totp.generate_otp(step + off), code):
            hit = step + off
    return hit


def verify_totp(secret: str | None, code: str | None, *, at: float | None = None) -> bool:
    """Accepts the current 30 s step and one step either side (clock drift). No replay check."""
    return totp_match_step(secret, code, at=at) is not None


def current_totp(secret: str, *, at: float | None = None) -> str:
    """Dev-only display helper (DISPUTES_DEV_SHOW_TOTP=1 in synthetic mode, never in demo/live)."""
    return pyotp.TOTP(secret).at(at if at is not None else time.time())


def provisioning_uri(secret: str, email: str) -> str:
    return pyotp.TOTP(secret).provisioning_uri(name=email, issuer_name="Dispute desk (synthetic)")


def dev_show_totp_enabled(mode: str) -> bool:
    """Never in live mode or in the hosted demo (it would reduce MFA to the password)."""
    return (os.environ.get("DISPUTES_DEV_SHOW_TOTP") == "1" and mode == "synthetic"
            and environment() not in ("demo", "live", "prod"))


def consume_totp(conn, user_id: str, secret: str | None, code: str | None, *, at: float | None = None) -> bool:
    """Verify and burn the code's step for this user (atomic). False on a bad or replayed code."""
    step = totp_match_step(secret, code, at=at)
    if step is None:
        return False
    row = conn.execute("UPDATE users SET totp_last_step = %s WHERE user_id = %s "
                       "AND (totp_last_step IS NULL OR totp_last_step < %s) RETURNING user_id",
                       (step, user_id, step)).fetchone()
    return row is not None


# ---------------------------------------------------------------- client address
def trusted_proxy_hops() -> int:
    try:
        return max(0, int(os.environ.get("DISPUTES_TRUSTED_PROXY_HOPS", "0")))
    except ValueError:
        return 0


def client_ip(peer: str | None, xff: str | None, hops: int | None = None) -> str:
    """Socket peer unless trusted proxies are configured; then the address `hops` entries from the
    right of X-Forwarded-For (entries to the left are client-controlled and ignored)."""
    hops = trusted_proxy_hops() if hops is None else hops
    peer = peer or "unknown"
    if hops <= 0 or not xff:
        return peer
    parts = [p.strip() for p in xff.split(",") if p.strip()]
    if len(parts) < hops:
        return peer
    cand = parts[-hops]
    try:
        return str(ipaddress.ip_address(cand))
    except ValueError:
        return peer


# ---------------------------------------------------------------- rate limiting / lockout
def _lock_account(conn, key: str) -> None:
    conn.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))", (key,))


def account_locked(conn, key: str) -> bool:
    """>= MAX_ACCOUNT_FAILURES failures in the window since the last full sign-in (TOTP success) or
    admin unlock. A correct password alone does NOT reset the count, so someone who knows the
    password cannot keep guessing TOTP codes by re-entering it."""
    r = conn.execute(
        "SELECT count(*) AS n FROM auth_attempts WHERE account_key = %s AND NOT success "
        "AND kind IN ('PASSWORD','TOTP') AND at > now() - make_interval(mins => %s) "
        "AND at > COALESCE((SELECT max(at) FROM auth_attempts WHERE account_key = %s AND success "
        "AND kind IN ('TOTP','UNLOCK')), '-infinity')",
        (key, FAILURE_WINDOW_MIN, key)).fetchone()
    return r["n"] >= MAX_ACCOUNT_FAILURES


def ip_throttled(conn, ip: str) -> bool:
    r = conn.execute("SELECT count(*) AS n FROM auth_attempts WHERE source_ip = %s AND NOT success "
                     "AND at > now() - make_interval(mins => %s)", (ip, FAILURE_WINDOW_MIN)).fetchone()
    return r["n"] >= MAX_IP_FAILURES


def record_attempt(conn, *, kind: str, key: str, ip: str, success: bool) -> None:
    conn.execute("INSERT INTO auth_attempts (kind, account_key, source_ip, success) VALUES (%s,%s,%s,%s)",
                 (kind, key, ip, success))


def unlock_account(conn, email: str, *, ip: str = "admin") -> None:
    """Admin unlock: a success marker resets the failure count (kind UNLOCK)."""
    record_attempt(conn, kind="UNLOCK", key=account_key(email), ip=ip, success=True)


def audit_if_lock_started(conn, key: str, user: dict | None, *, ip: str, kind: str) -> bool:
    """Call right after recording a failure that was made while the account was NOT locked: if the
    account is now locked, write one ACCOUNT_LOCKED audit event (R-18 v1.3: lockouts are audited).
    Only for existing users (an attacker spraying unknown emails cannot grow the audit log)."""
    if user is None or not account_locked(conn, key):
        return False
    from disputes.audit.chain import append_event
    from disputes.domain import ActorType
    append_event(conn, tenant_id=user.get("tenant_id") or "ops", case_id=None, event_type="ACCOUNT_LOCKED",
                 actor_type=ActorType.SYSTEM, actor_id="system:auth", actor_role=None,
                 payload={"user_id": user["user_id"], "after": kind, "source_ip": ip,
                          "max_failures": MAX_ACCOUNT_FAILURES, "window_min": FAILURE_WINDOW_MIN})
    return True


@dataclass(frozen=True)
class LoginResult:
    user: dict | None
    error: str | None          # None on success
    status: int                # 200 ok, 401 bad credentials, 429 locked/throttled


def authenticate_password(conn, email: str, password: str, *, ip: str = "unknown",
                          env: str | None = None) -> LoginResult:
    """Password step with lockout. Same message for unknown email, wrong password and inactive
    user; the lockout message is the same whether or not the email exists."""
    env = env or environment()
    key = account_key(email)
    with conn.transaction():
        _lock_account(conn, key)
        if ip_throttled(conn, ip) or account_locked(conn, key):
            record_attempt(conn, kind="PASSWORD", key=key, ip=ip, success=False)
            return LoginResult(None, LOCKED_ERROR, 429)
        row = conn.execute("SELECT * FROM users WHERE lower(email) = lower(%s)",
                           ((email or "").strip(),)).fetchone()
        if row is None:
            verify_password(password or "x", _DUMMY_HASH)     # equalise timing for unknown users
            ok = False
        else:
            ok = verify_password(password or "", row["password_hash"]) and row["active"]
        if ok and env == "demo" and any(verify_password(p, row["password_hash"]) for p in SEEDED_DEMO_PASSWORDS):
            # Seeded password on an internet-facing demo: refuse; the admin must issue a reset link.
            record_attempt(conn, kind="PASSWORD", key=key, ip=ip, success=False)
            return LoginResult(None, "This account still uses the published demo password. Ask an admin for a "
                                     "sign-in reset link.", 401)
        record_attempt(conn, kind="PASSWORD", key=key, ip=ip, success=False if not ok else True)
        if not ok:
            audit_if_lock_started(conn, key, row, ip=ip, kind="PASSWORD")
            return LoginResult(None, GENERIC_LOGIN_ERROR, 401)
        return LoginResult(row, None, 200)


_DUMMY_HASH = "scrypt$16384$8$1$" + "00" * 16 + "$" + "00" * 32


# ---------------------------------------------------------------- server-side sessions
class SessionStore:
    """Sessions in Postgres. Tokens are 256-bit random; only their SHA-256 is stored."""

    def create(self, conn, user_id: str, *, stage: str, ip: str | None = None,
               lifetime_s: int | None = None) -> tuple[str, dict]:
        if lifetime_s is None:
            lifetime_s = PENDING_MAX_AGE_S if stage == "MFA_PENDING" else SESSION_ABSOLUTE_HOURS * 3600
        token = secrets.token_urlsafe(32)
        row = conn.execute(
            "INSERT INTO web_sessions (session_hash, user_id, stage, csrf, expires_at, source_ip) "
            "VALUES (%s,%s,%s,%s, now() + make_interval(secs => %s), %s) RETURNING *",
            (token_hash(token), user_id, stage, secrets.token_urlsafe(24), lifetime_s, ip)).fetchone()
        return token, row

    def load(self, conn, token: str | None, *, stage: str = "ACTIVE", idle_timeout_s: int | None = None,
             touch: bool = True) -> dict | None:
        """The live session row (and touch last_seen), or None if missing, revoked, expired or idle."""
        if not token or len(token) > 200:
            return None
        idle = idle_timeout_s if idle_timeout_s is not None else 10 ** 9
        cond = ("session_hash = %s AND stage = %s AND revoked_at IS NULL AND expires_at > now() "
                "AND last_seen_at > now() - make_interval(secs => %s)")
        params = (token_hash(token), stage, idle)
        if touch:
            return conn.execute(f"UPDATE web_sessions SET last_seen_at = now() WHERE {cond} RETURNING *",
                                params).fetchone()
        return conn.execute(f"SELECT * FROM web_sessions WHERE {cond}", params).fetchone()

    def revoke(self, conn, token: str | None, reason: str) -> bool:
        if not token:
            return False
        r = conn.execute("UPDATE web_sessions SET revoked_at = now(), revoked_reason = %s "
                         "WHERE session_hash = %s AND revoked_at IS NULL RETURNING session_hash",
                         (reason, token_hash(token))).fetchone()
        return r is not None

    def revoke_user(self, conn, user_id: str, reason: str) -> int:
        rows = conn.execute("UPDATE web_sessions SET revoked_at = now(), revoked_reason = %s "
                            "WHERE user_id = %s AND revoked_at IS NULL RETURNING session_hash",
                            (reason, user_id)).fetchall()
        return len(rows)

    def mfa_failed(self, conn, token: str) -> int:
        """Count a bad code on a pending session; revoke it at the limit. Returns the new count."""
        r = conn.execute("UPDATE web_sessions SET mfa_failures = mfa_failures + 1 WHERE session_hash = %s "
                         "RETURNING mfa_failures", (token_hash(token),)).fetchone()
        n = r["mfa_failures"] if r else MAX_MFA_FAILURES_PER_PENDING
        if n >= MAX_MFA_FAILURES_PER_PENDING:
            self.revoke(conn, token, "too many MFA failures")
        return n

    def live_count(self, conn, user_id: str) -> int:
        return conn.execute("SELECT count(*) AS n FROM web_sessions WHERE user_id = %s AND revoked_at IS NULL "
                            "AND expires_at > now()", (user_id,)).fetchone()["n"]


# ---------------------------------------------------------------- invites (first login / reset)
def create_invite(conn, *, user_id: str, purpose: str, created_by: str) -> str:
    """Revoke the user's open invites and issue a new one. Returns the token (shown once)."""
    conn.execute("UPDATE user_invites SET revoked_at = now() WHERE user_id = %s AND used_at IS NULL "
                 "AND revoked_at IS NULL", (user_id,))
    token = secrets.token_urlsafe(32)
    conn.execute("INSERT INTO user_invites (token_hash, user_id, purpose, created_by, expires_at) "
                 "VALUES (%s,%s,%s,%s, now() + make_interval(hours => %s))",
                 (token_hash(token), user_id, purpose, created_by, INVITE_TTL_HOURS))
    return token


def load_invite(conn, token: str | None, *, for_update: bool = False) -> dict | None:
    """The open invite joined with its (active) user, or None."""
    if not token or len(token) > 200 or not re.fullmatch(r"[A-Za-z0-9_\-]+", token):
        return None
    return conn.execute(
        "SELECT i.*, u.email, u.display_name, u.role, u.active FROM user_invites i JOIN users u USING (user_id) "
        "WHERE i.token_hash = %s AND i.used_at IS NULL AND i.revoked_at IS NULL AND i.expires_at > now() "
        "AND u.active" + (" FOR UPDATE OF i" if for_update else ""), (token_hash(token),)).fetchone()


# ---------------------------------------------------------------- principal + authorisation
@dataclass(frozen=True)
class Principal:
    user_id: str
    email: str
    display_name: str
    role: Role
    home_tenant_id: str | None      # set only for CLIENT_VIEWER

    @property
    def is_staff(self) -> bool:
        return self.role in STAFF_ROLES

    @property
    def can_act(self) -> bool:
        return self.role in ACTING_ROLES


def load_principal(conn, user_id: str) -> Principal | None:
    row = conn.execute("SELECT user_id, email, display_name, role, tenant_id, active FROM users "
                       "WHERE user_id = %s", (user_id,)).fetchone()
    if row is None or not row["active"]:
        return None
    return Principal(row["user_id"], row["email"], row["display_name"], Role(row["role"]), row["tenant_id"])


def tenant_ids_for(conn, p: Principal) -> list[str]:
    """Client tenants this principal may see. ADMIN: all client tenants; other staff: their
    staff_tenant_access rows; CLIENT_VIEWER: only its own tenant. 'ops' is never a client tenant."""
    if p.role == Role.CLIENT_VIEWER:
        return [p.home_tenant_id] if p.home_tenant_id else []
    if p.role == Role.ADMIN:
        rows = conn.execute("SELECT tenant_id FROM tenants WHERE tenant_id <> 'ops' ORDER BY tenant_id").fetchall()
    else:
        rows = conn.execute("SELECT a.tenant_id FROM staff_tenant_access a JOIN tenants t USING (tenant_id) "
                            "WHERE a.user_id = %s AND a.tenant_id <> 'ops' ORDER BY a.tenant_id",
                            (p.user_id,)).fetchall()
    return [r["tenant_id"] for r in rows]


def staff_can_access_tenant(conn, p: Principal, tenant_id: str) -> bool:
    return p.is_staff and tenant_id in tenant_ids_for(conn, p)
