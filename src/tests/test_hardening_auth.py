"""Hardening: login rate limiting / lockout, generic errors, TOTP replay, server-side sessions
(rotation, revocation, idle and absolute expiry), cookie flags, trusted-proxy client address,
password policy, demo-environment rules. All data SYNTHETIC."""
from __future__ import annotations

import psycopg
import pytest
from fastapi.testclient import TestClient

from disputes.web import auth, demo
from test_web_support import A, app_factory, case, csrf_of, login, seeded  # noqa: F401

SPEC_EMAIL = "spec@ops.example"


def _pw(c, email=SPEC_EMAIL, pw=demo.DEMO_PASSWORD, headers=None):
    return c.post("/login", data={"email": email, "password": pw}, headers=headers or {}, follow_redirects=False)


def _forget_step(db_url, uid):
    with psycopg.connect(db_url) as c:
        c.execute("UPDATE users SET totp_last_step = NULL WHERE user_id = %s", (uid,))


# ------------------------------------------------------------------ lockout and generic errors
def test_account_lockout_after_five_failures_blocks_even_the_right_password(seeded, app_factory):
    c = TestClient(app_factory())
    for _ in range(auth.MAX_ACCOUNT_FAILURES):
        r = _pw(c, pw="wrong-password-x")
        assert r.status_code == 401 and auth.GENERIC_LOGIN_ERROR in r.text
    r = _pw(c)                                            # correct password, but locked
    assert r.status_code == 429 and "Too many sign-in attempts" in r.text
    assert "disputes_mfa_pending" not in r.headers.get("set-cookie", "")


def test_lockout_does_not_reveal_whether_an_email_exists(seeded, app_factory):
    c = TestClient(app_factory())
    known = [_pw(c, pw="nope-nope-nope") for _ in range(6)]
    unknown = [_pw(c, email="nobody-here@ops.example", pw="nope-nope-nope") for _ in range(6)]
    assert [r.status_code for r in known] == [r.status_code for r in unknown] == [401] * 5 + [429]
    assert auth.GENERIC_LOGIN_ERROR in known[0].text and auth.GENERIC_LOGIN_ERROR in unknown[0].text
    assert auth.LOCKED_ERROR in known[-1].text and auth.LOCKED_ERROR in unknown[-1].text
    inactive = TestClient(app_factory())
    with psycopg.connect(inactive.app.state.database_url) as conn:
        conn.execute("UPDATE users SET active = false WHERE user_id = 'u-sup2'")
    r = _pw(inactive, email="sup2@ops.example")        # right password, inactive account: same answer
    assert r.status_code == 401 and auth.GENERIC_LOGIN_ERROR in r.text


def test_totp_failures_count_toward_lockout_and_password_success_does_not_reset(seeded, app_factory):
    """Someone who knows the password cannot keep guessing codes by re-entering it."""
    c = TestClient(app_factory())
    for _ in range(auth.MAX_ACCOUNT_FAILURES):
        assert _pw(c).status_code == 303
        assert c.post("/login/mfa", data={"code": "000000"}, follow_redirects=False).status_code == 401
    assert _pw(c).status_code == 429


def test_pending_session_dies_after_mfa_failures(conn, seeded, app_factory):
    c = TestClient(app_factory())
    _pw(c)
    for _ in range(auth.MAX_MFA_FAILURES_PER_PENDING - 1):
        c.post("/login/mfa", data={"code": "000000"})
    c.post("/login/mfa", data={"code": "000000"})
    r = c.post("/login/mfa", data={"code": auth.current_totp(seeded["u-spec"])}, follow_redirects=False)
    assert r.status_code in (303, 429)
    assert r.headers.get("location") != "/ops"             # never signed in on that pending session


def test_admin_unlock_and_full_sign_in_reset_the_count(conn, seeded, app_factory):
    c = TestClient(app_factory())
    for _ in range(auth.MAX_ACCOUNT_FAILURES):
        _pw(c, pw="wrong-password-x")
    assert _pw(c).status_code == 429
    auth.unlock_account(conn, SPEC_EMAIL)
    conn.commit()
    login(c, seeded, "u-spec")
    assert c.get("/ops/t/synthetic-tenant-0/queue").status_code == 200


def test_per_ip_throttle_across_many_accounts(seeded, app_factory, monkeypatch):
    monkeypatch.setattr(auth, "MAX_IP_FAILURES", 4)
    c = TestClient(app_factory())
    for i in range(4):
        assert _pw(c, email=f"spray{i}@ops.example", pw="Spring2026!!").status_code == 401
    assert _pw(c).status_code == 429                         # a different, valid account is throttled too


def test_trusted_proxy_setting_controls_the_client_address(seeded, app_factory, monkeypatch):
    """Behind a load balancer, X-Forwarded-For decides the address only when hops are configured;
    otherwise a spoofed header cannot dodge the per-address throttle."""
    assert auth.client_ip("10.0.0.5", "1.2.3.4, 203.0.113.9", hops=0) == "10.0.0.5"
    assert auth.client_ip("10.0.0.5", "1.2.3.4, 203.0.113.9", hops=1) == "203.0.113.9"
    assert auth.client_ip("10.0.0.5", "203.0.113.9", hops=2) == "10.0.0.5"          # too few entries
    assert auth.client_ip("10.0.0.5", "not-an-ip", hops=1) == "10.0.0.5"
    monkeypatch.setattr(auth, "MAX_IP_FAILURES", 3)
    c = TestClient(app_factory())
    for i in range(3):
        _pw(c, email=f"x{i}@ops.example", pw="bad", headers={"X-Forwarded-For": f"198.51.100.{i}"})
    # hops=0: the spoofed header is ignored, so the same peer is throttled
    assert _pw(c, email="x9@ops.example", pw="bad", headers={"X-Forwarded-For": "198.51.100.77"}).status_code == 429
    monkeypatch.setenv("DISPUTES_TRUSTED_PROXY_HOPS", "1")
    assert _pw(c, email="x9@ops.example", pw="bad", headers={"X-Forwarded-For": "198.51.100.77"}).status_code == 401
    with psycopg.connect(c.app.state.database_url) as conn:
        ips = {r[0] for r in conn.execute("SELECT source_ip FROM auth_attempts").fetchall()}
    assert "198.51.100.77" in ips and "testclient" in ips


def test_attempt_rows_hold_no_raw_email(seeded, app_factory):
    c = TestClient(app_factory())
    _pw(c, pw="wrong")
    with psycopg.connect(c.app.state.database_url) as conn:
        rows = conn.execute("SELECT account_key FROM auth_attempts").fetchall()
    assert rows and all("@" not in r[0] and len(r[0]) == 64 for r in rows)


# ------------------------------------------------------------------ TOTP
def test_totp_code_cannot_be_replayed(seeded, app_factory):
    a = TestClient(app_factory())
    code = auth.current_totp(seeded["u-spec"])
    _pw(a)
    assert a.post("/login/mfa", data={"code": code}, follow_redirects=False).headers["location"] == "/ops"
    b = TestClient(app_factory())                            # an observer reuses the same code
    _pw(b)
    assert b.post("/login/mfa", data={"code": code}, follow_redirects=False).status_code == 401


def test_totp_step_matching_is_exact():
    s = auth.new_totp_secret()
    t = 1_800_000_000
    assert auth.totp_match_step(s, auth.current_totp(s, at=t), at=t) == t // 30
    assert auth.totp_match_step(s, auth.current_totp(s, at=t - 30), at=t) == t // 30 - 1
    assert auth.totp_match_step(s, auth.current_totp(s, at=t - 90), at=t) is None
    assert auth.totp_match_step(s, "12345", at=t) is None and auth.totp_match_step(None, "123456") is None


# ------------------------------------------------------------------ sessions
def test_session_id_rotates_at_password_step_and_after_mfa(seeded, app_factory):
    c = TestClient(app_factory())
    planted = "attacker-chosen-session-id-" + "x" * 20
    c.cookies.set(auth.SESSION_COOKIE, planted)
    r = _pw(c)
    pending = r.cookies.get(auth.PENDING_COOKIE)
    assert pending and pending != planted
    _forget_step(c.app.state.database_url, "u-spec")
    r = c.post("/login/mfa", data={"code": auth.current_totp(seeded["u-spec"])}, follow_redirects=False)
    active = r.cookies.get(auth.SESSION_COOKIE)
    assert active and active not in (planted, pending)
    with psycopg.connect(c.app.state.database_url) as conn:
        rows = conn.execute("SELECT session_hash, stage, revoked_at FROM web_sessions").fetchall()
    assert {row[0] for row in rows} == {auth.token_hash(pending), auth.token_hash(active)}   # planted never stored
    assert [row for row in rows if row[0] == auth.token_hash(pending)][0][2] is not None      # pending revoked
    # the pending token cannot be used as a full session
    x = TestClient(app_factory())
    x.cookies.set(auth.SESSION_COOKIE, pending)
    assert x.get("/ops", follow_redirects=False).headers["location"] == "/login"


def test_logout_revokes_server_side_so_a_copied_cookie_dies(seeded, app_factory):
    c = login(TestClient(app_factory()), seeded, "u-spec")
    stolen = c.cookies.get(auth.SESSION_COOKIE)
    c.post("/logout")
    thief = TestClient(app_factory())
    thief.cookies.set(auth.SESSION_COOKIE, stolen)
    assert thief.get("/ops", follow_redirects=False).headers["location"] == "/login"


def test_deactivation_and_admin_revoke_kill_sessions(conn, seeded, app_factory):
    from disputes.web import admin_users
    spec = login(TestClient(app_factory()), seeded, "u-spec")
    sup = login(TestClient(app_factory()), seeded, "u-sup1")
    admin_users.revoke_sessions(conn, actor_id="u-admin", actor_role="ADMIN", user_id="u-spec")
    admin_users.deactivate(conn, actor_id="u-admin", actor_role="ADMIN", user_id="u-sup1")
    conn.commit()
    assert spec.get("/ops", follow_redirects=False).headers["location"] == "/login"
    assert sup.get("/ops", follow_redirects=False).headers["location"] == "/login"
    assert _pw(TestClient(app_factory()), email="sup1@ops.example").status_code == 401


def test_absolute_lifetime_even_when_active(conn, seeded, app_factory):
    c = login(TestClient(app_factory()), seeded, "u-spec")
    assert c.get("/ops", follow_redirects=False).status_code == 303
    conn.execute("UPDATE web_sessions SET created_at = now() - interval '13 hours', "
                 "expires_at = now() - interval '1 hour' WHERE user_id = 'u-spec' AND stage = 'ACTIVE'")
    conn.commit()
    assert c.get("/ops", follow_redirects=False).headers["location"] == "/login"


def test_cookie_flags_with_cookie_secure(seeded, app_factory, monkeypatch):
    monkeypatch.setenv("DISPUTES_COOKIE_SECURE", "1")
    c = TestClient(app_factory(), base_url="https://testserver")
    r = _pw(c)
    sc = r.headers["set-cookie"].lower()
    assert "httponly" in sc and "secure" in sc and "samesite=lax" in sc and "path=/login" in sc
    _forget_step(c.app.state.database_url, "u-spec")
    r = c.post("/login/mfa", data={"code": auth.current_totp(seeded["u-spec"])}, follow_redirects=False)
    sc = [v for k, v in r.headers.multi_items() if k == "set-cookie" and "__host-" in v.lower()][0].lower()
    assert sc.startswith("__host-disputes_session=") and "secure" in sc and "httponly" in sc and "path=/" in sc
    assert "domain=" not in sc
    page = c.get("/ops/t/synthetic-tenant-0/queue")
    assert page.status_code == 200
    assert page.headers["strict-transport-security"].startswith("max-age=31536000")


def test_no_hsts_without_cookie_secure(seeded, app_factory):
    assert "strict-transport-security" not in TestClient(app_factory()).get("/login").headers


# ------------------------------------------------------------------ password policy and demo env
def test_password_policy():
    assert auth.password_policy_errors("short", env="dev")
    assert auth.password_policy_errors("aaaaaaaaaaaaaaaa", env="dev")            # too few distinct chars
    assert auth.password_policy_errors("password1234", env="dev")
    assert auth.password_policy_errors("jo.smith@ex.com", email="jo.smith@ex.com", env="dev")
    assert not auth.password_policy_errors("a-long and odd phrase 42", env="dev")
    assert demo.DEMO_PASSWORD in auth.SEEDED_DEMO_PASSWORDS
    assert auth.password_policy_errors(demo.DEMO_PASSWORD, env="demo")
    assert not [e for e in auth.password_policy_errors(demo.DEMO_PASSWORD, env="dev") if "published" in e]


def test_seeded_demo_password_refused_at_login_only_in_demo_env(seeded, app_factory, monkeypatch):
    assert _pw(TestClient(app_factory())).status_code == 303                       # dev: allowed (local demo)
    monkeypatch.setenv("DISPUTES_ENV", "demo")
    r = _pw(TestClient(app_factory()))
    assert r.status_code == 401 and "published demo password" in r.text


def test_dev_totp_display_never_in_demo_env(monkeypatch):
    monkeypatch.setenv("DISPUTES_DEV_SHOW_TOTP", "1")
    monkeypatch.setenv("DISPUTES_ENV", "dev")
    assert auth.dev_show_totp_enabled("synthetic")
    monkeypatch.setenv("DISPUTES_ENV", "demo")
    assert not auth.dev_show_totp_enabled("synthetic")


def test_unusable_password_never_verifies():
    assert not auth.verify_password("", auth.UNUSABLE_PASSWORD)
    assert not auth.verify_password("!invite", auth.UNUSABLE_PASSWORD)
    long_pw = "x" * (auth.MAX_PASSWORD_LEN + 1)
    assert not auth.verify_password(long_pw, auth.hash_password(long_pw))       # over-long input is refused


def test_lockout_is_audited_once_for_existing_accounts_only(seeded, app_factory):
    c = TestClient(app_factory())
    for _ in range(auth.MAX_ACCOUNT_FAILURES + 2):
        _pw(c, pw="wrong-password-x")
        _pw(c, email="ghost@ops.example", pw="wrong-password-x")
    with psycopg.connect(c.app.state.database_url) as conn:
        rows = conn.execute("SELECT tenant_id, payload FROM audit_events WHERE event_type = 'ACCOUNT_LOCKED'").fetchall()
    assert len(rows) == 1 and rows[0][1]["user_id"] == "u-spec" and rows[0][0] == "ops"
