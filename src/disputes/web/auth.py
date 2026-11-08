"""R-18 authentication and authorisation for the web surfaces. OWNER: web agent.

- Passwords: stdlib `hashlib.scrypt` (no new dependency). Stored as
  "scrypt$<n>$<r>$<p>$<salt_hex>$<hash_hex>"; verification is constant-time.
- MFA: TOTP (RFC 6238) via `pyotp`. Every login needs password + TOTP; users without a TOTP
  secret cannot log in (no self-enrolment in the prototype).
- Sessions: signed cookies (itsdangerous, key = Settings.session_secret). The cookie carries
  user_id, a CSRF token and `last_seen`; it is re-issued on each request and refused once the
  idle gap exceeds `Config.session_idle_timeout_min` (default 30). The user row is re-read on every
  request, so deactivating a user or changing their role takes effect immediately.
- Roles are checked on the server (`require_staff`, `require_client`, `tenant_ids_for`).

`cli seed-demo` (platform-core) looks up `hash_password` and `new_totp_secret` by name.
"""
from __future__ import annotations

import hashlib
import hmac
import os
import secrets
import time
from dataclasses import dataclass

import pyotp
from itsdangerous import BadSignature, URLSafeSerializer

from disputes.domain import Role

# scrypt parameters: n=2**14, r=8, p=1 (~16 MiB, ~50 ms). Stored with the hash so they can rise later.
_SCRYPT_N, _SCRYPT_R, _SCRYPT_P, _DKLEN = 2 ** 14, 8, 1, 32

STAFF_ROLES = frozenset({Role.SPECIALIST, Role.SUPERVISOR, Role.ADMIN, Role.AUDITOR})
ACTING_ROLES = frozenset({Role.SPECIALIST, Role.SUPERVISOR, Role.ADMIN})   # may change cases
SESSION_COOKIE = "disputes_session"
PENDING_COOKIE = "disputes_mfa_pending"
PENDING_MAX_AGE_S = 300


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
        if algo != "scrypt":
            return False
        expected = bytes.fromhex(hash_hex)
        dk = hashlib.scrypt((pw or "").encode("utf-8"), salt=bytes.fromhex(salt_hex), n=int(n), r=int(r),
                            p=int(p), dklen=len(expected))
    except (ValueError, AttributeError):
        return False
    return hmac.compare_digest(dk, expected)


# ---------------------------------------------------------------- TOTP
def new_totp_secret() -> str:
    return pyotp.random_base32()


def verify_totp(secret: str | None, code: str | None, *, at: float | None = None) -> bool:
    """Accepts the current 30 s step and one step either side (clock drift)."""
    if not secret or not code:
        return False
    code = code.strip().replace(" ", "")
    if not (code.isdigit() and len(code) == 6):
        return False
    return pyotp.TOTP(secret).verify(code, for_time=at if at is not None else time.time(), valid_window=1)


def current_totp(secret: str, *, at: float | None = None) -> str:
    """Dev-only display helper (DISPUTES_DEV_SHOW_TOTP=1 in synthetic mode)."""
    return pyotp.TOTP(secret).at(at if at is not None else time.time())


def dev_show_totp_enabled(mode: str) -> bool:
    """Never in live mode, whatever the environment says."""
    return os.environ.get("DISPUTES_DEV_SHOW_TOTP") == "1" and mode == "synthetic"


# ---------------------------------------------------------------- sessions
class SessionCodec:
    """Signed, idle-timed session cookie. Stateless: logout clears the cookie (see notes: limit)."""

    def __init__(self, secret: str):
        self._s = URLSafeSerializer(secret, salt="disputes.session.v1")
        self._p = URLSafeSerializer(secret, salt="disputes.mfa-pending.v1")

    def new_session(self, user_id: str, *, now: float | None = None) -> dict:
        now = time.time() if now is None else now
        return {"uid": user_id, "csrf": secrets.token_urlsafe(24), "iat": int(now), "seen": int(now)}

    def dump(self, sess: dict) -> str:
        return self._s.dumps(sess)

    def load(self, token: str | None, *, idle_timeout_s: int, now: float | None = None) -> dict | None:
        """The session, or None if missing, tampered or idle too long."""
        if not token:
            return None
        try:
            sess = self._s.loads(token)
        except BadSignature:
            return None
        now = time.time() if now is None else now
        if not isinstance(sess, dict) or "uid" not in sess or now - sess.get("seen", 0) > idle_timeout_s:
            return None
        return sess

    def touch(self, sess: dict, *, now: float | None = None) -> dict:
        return {**sess, "seen": int(time.time() if now is None else now)}

    def dump_pending(self, user_id: str, *, now: float | None = None) -> str:
        return self._p.dumps({"uid": user_id, "at": int(time.time() if now is None else now)})

    def load_pending(self, token: str | None, *, now: float | None = None) -> str | None:
        if not token:
            return None
        try:
            d = self._p.loads(token)
        except BadSignature:
            return None
        now = time.time() if now is None else now
        if now - d.get("at", 0) > PENDING_MAX_AGE_S:
            return None
        return d.get("uid")


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


def authenticate_password(conn, email: str, password: str) -> dict | None:
    """The user row if the password matches an active user; None otherwise (same answer for both)."""
    row = conn.execute("SELECT * FROM users WHERE lower(email) = lower(%s)", ((email or "").strip(),)).fetchone()
    if row is None:
        verify_password(password or "x", _DUMMY_HASH)     # equalise timing for unknown users
        return None
    if not row["active"] or not verify_password(password or "", row["password_hash"]):
        return None
    return row


_DUMMY_HASH = "scrypt$16384$8$1$" + "00" * 16 + "$" + "00" * 32


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
