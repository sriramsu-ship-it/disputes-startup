"""User administration (R-18, R-21, R-38, R-39). OWNER: hardening.

ADMIN-only service layer behind /ops/admin/users (HTTP routes in app.py are thin wrappers):
- create a user: staff (SPECIALIST / SUPERVISOR / AUDITOR / ADMIN) with client-tenant assignments,
  or CLIENT_VIEWER bound to exactly one client tenant. The user gets no password and no TOTP;
  the ADMIN receives a one-time invite link (shown once, only its hash is stored) to hand over
  out of band. We never send email.
- deactivate (kills every session at once), reset sign-in (clears password + TOTP, revokes
  sessions, new invite link), revoke sessions, unlock after lockout, change staff tenant access.
- every change writes an audit event (tenant 'ops', actor = the ADMIN) in the same transaction.
- an ADMIN cannot deactivate or reset themselves (avoids locking the last admin out by mistake).
"""
from __future__ import annotations

import re
import secrets

from disputes.audit.chain import append_event
from disputes.domain import ActorType, Role
from disputes.web import auth

PLATFORM_TENANT = "ops"
STAFF_ROLE_VALUES = ("SPECIALIST", "SUPERVISOR", "AUDITOR", "ADMIN")
_EMAIL = re.compile(r"^[^@\s<>\"']{1,64}@[A-Za-z0-9.-]{1,180}\.[A-Za-z]{2,24}$")


class AdminError(ValueError):
    pass


class AdminForbidden(PermissionError):
    pass


def _audit(conn, actor_id: str, actor_role, event_type: str, payload: dict) -> None:
    append_event(conn, tenant_id=PLATFORM_TENANT, case_id=None, event_type=event_type,
                 actor_type=ActorType.HUMAN if not str(actor_id).startswith("system:") else ActorType.SYSTEM,
                 actor_id=actor_id, actor_role=str(actor_role) if actor_role else None, payload=payload)


def client_tenants(conn) -> list[dict]:
    return conn.execute("SELECT tenant_id, display_name FROM tenants WHERE tenant_id <> 'ops' "
                        "ORDER BY tenant_id").fetchall()


def _valid_tenants(conn, tenants) -> list[str]:
    known = {r["tenant_id"] for r in client_tenants(conn)}
    out = sorted({str(t) for t in tenants or [] if str(t)})
    bad = [t for t in out if t not in known]
    if bad:
        raise AdminError(f"unknown client tenant(s): {', '.join(bad)}")
    return out


def invite_path(token: str) -> str:
    return f"/invite/{token}"


def create_user(conn, *, actor_id: str, actor_role, email: str, display_name: str, role: str,
                client_tenant: str | None, staff_tenants) -> dict:
    email = (email or "").strip()
    display_name = (display_name or "").strip()
    if not _EMAIL.match(email):
        raise AdminError("enter a valid email address")
    if not (1 <= len(display_name) <= 100):
        raise AdminError("display name must be 1-100 characters")
    if role not in (*STAFF_ROLE_VALUES, Role.CLIENT_VIEWER.value):
        raise AdminError("unknown role")
    with conn.transaction():
        if conn.execute("SELECT 1 FROM users WHERE lower(email) = lower(%s)", (email,)).fetchone():
            raise AdminError("a user with that email already exists")
        tenant = None
        access: list[str] = []
        if role == Role.CLIENT_VIEWER.value:
            ts = _valid_tenants(conn, [client_tenant] if client_tenant else [])
            if len(ts) != 1:
                raise AdminError("a client viewer must be bound to exactly one client tenant")
            tenant = ts[0]
        elif role != Role.ADMIN.value:          # ADMIN sees every client tenant (auth.tenant_ids_for)
            access = _valid_tenants(conn, staff_tenants)
        uid = "u-" + secrets.token_hex(6)
        conn.execute("INSERT INTO users (user_id, email, display_name, role, tenant_id, password_hash, totp_secret) "
                     "VALUES (%s,%s,%s,%s,%s,%s,NULL)", (uid, email, display_name, role, tenant, auth.UNUSABLE_PASSWORD))
        for t in access:
            conn.execute("INSERT INTO staff_tenant_access (user_id, tenant_id) VALUES (%s,%s)", (uid, t))
        token = auth.create_invite(conn, user_id=uid, purpose="INVITE", created_by=actor_id)
        _audit(conn, actor_id, actor_role, "USER_CREATED",
               {"user_id": uid, "role": role, "client_tenant": tenant, "staff_tenants": access,
                "invite_issued": True, "invite_ttl_hours": auth.INVITE_TTL_HOURS})
    return {"user_id": uid, "invite_path": invite_path(token)}


def _target(conn, user_id: str) -> dict:
    row = conn.execute("SELECT * FROM users WHERE user_id = %s FOR UPDATE", (user_id,)).fetchone()
    if row is None:
        raise AdminError("no such user")
    return row


def _not_self(actor_id: str, user_id: str, what: str) -> None:
    if actor_id == user_id:
        raise AdminForbidden(f"you cannot {what} your own account; ask another admin")


def deactivate(conn, *, actor_id: str, actor_role, user_id: str, reason: str = "") -> int:
    _not_self(actor_id, user_id, "deactivate")
    with conn.transaction():
        u = _target(conn, user_id)
        if not u["active"]:
            raise AdminError("user is already inactive")
        conn.execute("UPDATE users SET active = false WHERE user_id = %s", (user_id,))
        n = auth.SessionStore().revoke_user(conn, user_id, "user deactivated")
        conn.execute("UPDATE user_invites SET revoked_at = now() WHERE user_id = %s AND used_at IS NULL "
                     "AND revoked_at IS NULL", (user_id,))
        _audit(conn, actor_id, actor_role, "USER_DEACTIVATED",
               {"user_id": user_id, "sessions_revoked": n, "reason": (reason or "").strip() or None})
    return n


def reset_signin(conn, *, actor_id: str, actor_role, user_id: str) -> dict:
    """Clears password and TOTP, revokes sessions and issues a RESET invite (lost authenticator).
    Reactivates nothing: an inactive user stays inactive."""
    _not_self(actor_id, user_id, "reset")
    with conn.transaction():
        u = _target(conn, user_id)
        if not u["active"]:
            raise AdminError("user is inactive")
        conn.execute("UPDATE users SET password_hash = %s, totp_secret = NULL, totp_last_step = NULL "
                     "WHERE user_id = %s", (auth.UNUSABLE_PASSWORD, user_id))
        n = auth.SessionStore().revoke_user(conn, user_id, "sign-in reset by admin")
        token = auth.create_invite(conn, user_id=user_id, purpose="RESET", created_by=actor_id)
        _audit(conn, actor_id, actor_role, "USER_SIGNIN_RESET", {"user_id": user_id, "sessions_revoked": n,
                                                                 "mfa_cleared": True, "password_cleared": True})
    return {"user_id": user_id, "invite_path": invite_path(token), "sessions_revoked": n}


def revoke_sessions(conn, *, actor_id: str, actor_role, user_id: str) -> int:
    with conn.transaction():
        _target(conn, user_id)
        n = auth.SessionStore().revoke_user(conn, user_id, "revoked by admin")
        _audit(conn, actor_id, actor_role, "USER_SESSIONS_REVOKED", {"user_id": user_id, "sessions_revoked": n})
    return n


def unlock(conn, *, actor_id: str, actor_role, user_id: str) -> None:
    with conn.transaction():
        u = _target(conn, user_id)
        auth.unlock_account(conn, u["email"])
        _audit(conn, actor_id, actor_role, "USER_UNLOCKED", {"user_id": user_id})


def set_staff_access(conn, *, actor_id: str, actor_role, user_id: str, tenants) -> list[str]:
    """R-38: replace a staff user's client-tenant assignments (old and new are audited)."""
    with conn.transaction():
        u = _target(conn, user_id)
        if u["role"] in (Role.CLIENT_VIEWER.value, Role.ADMIN.value):
            raise AdminError("tenant access applies to SPECIALIST, SUPERVISOR and AUDITOR users only")
        new = _valid_tenants(conn, tenants)
        old = [r["tenant_id"] for r in conn.execute(
            "SELECT tenant_id FROM staff_tenant_access WHERE user_id = %s ORDER BY tenant_id", (user_id,)).fetchall()]
        if old == new:
            raise AdminError("no change")
        conn.execute("DELETE FROM staff_tenant_access WHERE user_id = %s", (user_id,))
        for t in new:
            conn.execute("INSERT INTO staff_tenant_access (user_id, tenant_id) VALUES (%s,%s)", (user_id, t))
        _audit(conn, actor_id, actor_role, "STAFF_ACCESS_CHANGED", {"user_id": user_id, "old": old, "new": new})
    return new


def list_users(conn) -> list[dict]:
    rows = conn.execute(
        "SELECT u.user_id, u.email, u.display_name, u.role, u.tenant_id, u.active, "
        "(u.totp_secret IS NOT NULL) AS mfa_enrolled, (u.password_hash <> %s) AS has_password, "
        "COALESCE((SELECT array_agg(a.tenant_id ORDER BY a.tenant_id) FROM staff_tenant_access a "
        "          WHERE a.user_id = u.user_id), '{}') AS staff_tenants, "
        "(SELECT count(*) FROM web_sessions s WHERE s.user_id = u.user_id AND s.revoked_at IS NULL "
        " AND s.expires_at > now() AND s.stage = 'ACTIVE') AS live_sessions, "
        "EXISTS (SELECT 1 FROM user_invites i WHERE i.user_id = u.user_id AND i.used_at IS NULL "
        "        AND i.revoked_at IS NULL AND i.expires_at > now()) AS invite_open "
        "FROM users u ORDER BY u.role, u.email", (auth.UNUSABLE_PASSWORD,)).fetchall()
    out = []
    for r in rows:
        r = dict(r)
        r["locked"] = auth.account_locked(conn, auth.account_key(r["email"]))
        out.append(r)
    return out


def complete_invite(conn, *, token: str, password: str, confirm: str, code: str, ip: str) -> dict:
    """First login / reset: set the password and enrol TOTP in one step. Raises AdminError with a
    user-facing message. On success the invite is used, sessions are revoked, and it is audited."""
    with conn.transaction():
        inv = auth.load_invite(conn, token, for_update=True)
        if inv is None:
            auth.record_attempt(conn, kind="INVITE", key="invite", ip=ip, success=False)
            raise AdminError("This link is not valid any more. Ask an admin for a new one.")
        errs = auth.password_policy_errors(password, email=inv["email"])
        if password != confirm:
            errs.append("The two passwords do not match.")
        if errs:
            raise AdminError(" ".join(errs))
        step = auth.totp_match_step(inv["pending_totp_secret"], code)
        if step is None:
            auth.record_attempt(conn, kind="INVITE", key="invite", ip=ip, success=False)
            raise AdminError("That code is not valid. Add the key to your authenticator app and enter the "
                             "6-digit code it shows.")
        conn.execute("UPDATE users SET password_hash = %s, totp_secret = %s, totp_last_step = %s WHERE user_id = %s",
                     (auth.hash_password(password), inv["pending_totp_secret"], step, inv["user_id"]))
        conn.execute("UPDATE user_invites SET used_at = now() WHERE token_hash = %s", (inv["token_hash"],))
        n = auth.SessionStore().revoke_user(conn, inv["user_id"], "credentials set from invite")
        append_event(conn, tenant_id=PLATFORM_TENANT, case_id=None, event_type="USER_ENROLLED",
                     actor_type=ActorType.HUMAN, actor_id=inv["user_id"], actor_role=inv["role"],
                     payload={"user_id": inv["user_id"], "purpose": inv["purpose"], "mfa": "TOTP",
                              "sessions_revoked": n})
    return {"user_id": inv["user_id"]}


def invite_view(conn, token: str) -> dict | None:
    """The invite page model; creates the pending TOTP secret on first view."""
    with conn.transaction():
        inv = auth.load_invite(conn, token, for_update=True)
        if inv is None:
            return None
        secret = inv["pending_totp_secret"]
        if not secret:
            secret = auth.new_totp_secret()
            conn.execute("UPDATE user_invites SET pending_totp_secret = %s WHERE token_hash = %s",
                         (secret, inv["token_hash"]))
    return {"email": inv["email"], "display_name": inv["display_name"], "purpose": inv["purpose"],
            "secret": secret, "secret_grouped": " ".join(secret[i:i + 4] for i in range(0, len(secret), 4)),
            "uri": auth.provisioning_uri(secret, inv["email"]), "min_len": auth.MIN_PASSWORD_LEN}
