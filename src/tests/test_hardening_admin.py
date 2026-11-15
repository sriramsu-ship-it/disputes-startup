"""Hardening: ADMIN user administration (create staff / client viewer, deactivate, reset sign-in,
revoke, unlock, tenant access), invite-based first login with TOTP enrolment, audit events.
SYNTHETIC data only."""
from __future__ import annotations

import re

import psycopg
import pyotp
from fastapi.testclient import TestClient

from disputes.web import admin_users, auth, demo
from test_web_support import A, B, app_factory, csrf_of, login, seeded  # noqa: F401

NEW_PW = "a long synthetic phrase 77"


def _events(db_url, etype):
    with psycopg.connect(db_url) as c:
        return [r[0] for r in c.execute("SELECT payload FROM audit_events WHERE event_type = %s ORDER BY event_id",
                                        (etype,)).fetchall()]


def _invite_from(html: str) -> str:
    m = re.search(r"(/invite/[A-Za-z0-9_\-]+)", html)
    assert m, "no invite link on the page"
    return m.group(1)


def _enrol(c: TestClient, path: str, pw: str = NEW_PW, code_offset: int = 0):
    page = c.get(path)
    assert page.status_code == 200 and page.headers["cache-control"] == "no-store"
    secret = re.search(r'data-testid="totp-secret">([A-Z2-7 ]+)<', page.text).group(1).replace(" ", "")
    uri = re.search(r'data-testid="totp-uri">([^<]+)<', page.text).group(1)
    assert uri.startswith("otpauth://totp/") and secret in uri
    code = pyotp.TOTP(secret).now()
    return c.post(path, data={"password": pw, "confirm": pw, "code": code}, follow_redirects=False), secret


def test_admin_creates_staff_user_who_enrols_and_signs_in(conn, seeded, app_factory):
    app = app_factory()
    adm = login(TestClient(app), seeded, "u-admin")
    r = adm.post("/ops/admin/users", data={"csrf": csrf_of(adm), "email": "new.analyst@ops.example",
                                           "display_name": "New Analyst (SYNTHETIC)", "role": "SPECIALIST",
                                           "staff_tenants": [A]})
    assert r.status_code == 200 and 'data-testid="invite-link"' in r.text
    path = _invite_from(r.text)
    with psycopg.connect(app.state.database_url) as c:
        u = c.execute("SELECT user_id, password_hash, totp_secret FROM users WHERE email = 'new.analyst@ops.example'"
                      ).fetchone()
        stored = c.execute("SELECT token_hash FROM user_invites WHERE user_id = %s", (u[0],)).fetchone()[0]
    assert u[1] == auth.UNUSABLE_PASSWORD and u[2] is None
    assert stored == auth.token_hash(path.rsplit("/", 1)[1]) and path.rsplit("/", 1)[1] not in stored
    # before enrolment the account cannot sign in
    assert TestClient(app).post("/login", data={"email": "new.analyst@ops.example", "password": ""},
                                follow_redirects=False).status_code == 401
    new = TestClient(app)
    r, secret = _enrol(new, path)
    assert r.status_code == 303 and r.headers["location"] == "/login?enrolled=1"
    assert new.get(path).status_code == 404                                   # one-time
    r = new.post("/login", data={"email": "new.analyst@ops.example", "password": NEW_PW}, follow_redirects=False)
    assert r.status_code == 303
    with psycopg.connect(app.state.database_url) as c:
        c.execute("UPDATE users SET totp_last_step = NULL WHERE user_id = %s", (u[0],))
    r = new.post("/login/mfa", data={"code": pyotp.TOTP(secret).now()}, follow_redirects=False)
    assert r.headers["location"] == "/ops"
    assert new.get(f"/ops/t/{A}/queue").status_code == 200 and new.get(f"/ops/t/{B}/queue").status_code == 404
    created = _events(app.state.database_url, "USER_CREATED")[-1]
    assert created["role"] == "SPECIALIST" and created["staff_tenants"] == [A]
    assert _events(app.state.database_url, "USER_ENROLLED")[-1]["mfa"] == "TOTP"
    assert any(e["user_id"] == u[0] for e in _events(app.state.database_url, "SIGNED_IN"))


def test_client_viewer_must_bind_exactly_one_tenant(conn, seeded):
    try:
        admin_users.create_user(conn, actor_id="u-admin", actor_role="ADMIN", email="cv@lender-a.example",
                                display_name="CV", role="CLIENT_VIEWER", client_tenant=None, staff_tenants=[])
        raise AssertionError("expected AdminError")
    except admin_users.AdminError:
        pass
    for bad in ("ops", "no-such-tenant"):
        try:
            admin_users.create_user(conn, actor_id="u-admin", actor_role="ADMIN", email=f"cv-{bad}@x.example",
                                    display_name="CV", role="CLIENT_VIEWER", client_tenant=bad, staff_tenants=[])
            raise AssertionError("expected AdminError")
        except admin_users.AdminError:
            pass
    out = admin_users.create_user(conn, actor_id="u-admin", actor_role="ADMIN", email="cv@lender-a.example",
                                  display_name="CV", role="CLIENT_VIEWER", client_tenant=A, staff_tenants=[B])
    row = conn.execute("SELECT tenant_id FROM users WHERE user_id = %s", (out["user_id"],)).fetchone()
    assert row["tenant_id"] == A
    assert not conn.execute("SELECT 1 FROM staff_tenant_access WHERE user_id = %s", (out["user_id"],)).fetchone()
    try:   # duplicate email, case-insensitive
        admin_users.create_user(conn, actor_id="u-admin", actor_role="ADMIN", email="CV@Lender-A.example",
                                display_name="CV2", role="SPECIALIST", client_tenant=None, staff_tenants=[])
        raise AssertionError("expected AdminError")
    except admin_users.AdminError:
        pass


def test_invite_rejects_weak_password_wrong_code_and_mismatch(seeded, app_factory, monkeypatch):
    from disputes.db.core import connect
    app = app_factory()
    with connect(app.state.database_url) as c:
        out = admin_users.create_user(c, actor_id="u-admin", actor_role="ADMIN", email="weak@ops.example",
                                      display_name="Weak", role="AUDITOR", client_tenant=None, staff_tenants=[A])
    c = TestClient(app)
    path = out["invite_path"]
    c.get(path)
    assert c.post(path, data={"password": "short", "confirm": "short", "code": "123456"}).status_code == 400
    assert c.post(path, data={"password": NEW_PW, "confirm": NEW_PW + "x", "code": "123456"}).status_code == 400
    r = c.post(path, data={"password": NEW_PW, "confirm": NEW_PW, "code": "000000"})
    assert r.status_code == 400 and "code is not valid" in r.text
    monkeypatch.setenv("DISPUTES_ENV", "demo")
    r = c.post(path, data={"password": demo.DEMO_PASSWORD, "confirm": demo.DEMO_PASSWORD, "code": "000000"})
    assert r.status_code == 400 and "published with the demo data" in r.text
    assert c.get("/invite/not-a-real-token").status_code == 404
    assert c.post("/invite/not-a-real-token", data={"password": NEW_PW, "confirm": NEW_PW,
                                                    "code": "1"}).status_code == 404


def test_expired_invite_is_refused(conn, seeded):
    out = admin_users.create_user(conn, actor_id="u-admin", actor_role="ADMIN", email="late@ops.example",
                                  display_name="Late", role="SPECIALIST", client_tenant=None, staff_tenants=[])
    conn.execute("UPDATE user_invites SET expires_at = now() - interval '1 minute'")
    assert admin_users.invite_view(conn, out["invite_path"].rsplit("/", 1)[1]) is None


def test_reset_signin_clears_mfa_revokes_sessions_and_issues_new_link(seeded, app_factory):
    app = app_factory()
    spec = login(TestClient(app), seeded, "u-spec")
    adm = login(TestClient(app), seeded, "u-admin")
    r = adm.post("/ops/admin/users/u-spec/reset", data={"csrf": csrf_of(adm)})
    assert r.status_code == 200
    path = _invite_from(r.text)
    assert spec.get("/ops", follow_redirects=False).headers["location"] == "/login"
    assert TestClient(app).post("/login", data={"email": "spec@ops.example", "password": demo.DEMO_PASSWORD},
                                follow_redirects=False).status_code == 401           # old password cleared
    r, _ = _enrol(TestClient(app), path)
    assert r.status_code == 303
    ev = _events(app.state.database_url, "USER_SIGNIN_RESET")[-1]
    assert ev["user_id"] == "u-spec" and ev["mfa_cleared"] and ev["sessions_revoked"] >= 1


def test_admin_cannot_deactivate_or_reset_self_and_non_admin_gets_403(seeded, app_factory):
    app = app_factory()
    adm = login(TestClient(app), seeded, "u-admin")
    assert adm.post("/ops/admin/users/u-admin/deactivate", data={"csrf": csrf_of(adm)}).status_code == 403
    assert adm.post("/ops/admin/users/u-admin/reset", data={"csrf": csrf_of(adm)}).status_code == 403
    sup = login(TestClient(app), seeded, "u-sup1")
    assert sup.get("/ops/admin/users").status_code == 403
    assert sup.post("/ops/admin/users", data={"csrf": csrf_of(sup), "email": "evil@x.example",
                                              "display_name": "E", "role": "ADMIN"}).status_code == 403
    assert sup.post("/ops/admin/users/u-spec/deactivate", data={"csrf": csrf_of(sup)}).status_code == 403
    with psycopg.connect(app.state.database_url) as c:
        assert c.execute("SELECT active FROM users WHERE user_id = 'u-spec'").fetchone()[0] is True
        assert not c.execute("SELECT 1 FROM users WHERE email = 'evil@x.example'").fetchone()


def test_staff_access_change_is_audited_and_takes_effect(seeded, app_factory):
    app = app_factory()
    specb = login(TestClient(app), seeded, "u-spec-b")
    assert specb.get(f"/ops/t/{A}/queue").status_code == 404
    adm = login(TestClient(app), seeded, "u-admin")
    r = adm.post("/ops/admin/users/u-spec-b/access", data={"csrf": csrf_of(adm), "staff_tenants": [A, B]})
    assert r.status_code == 200
    assert specb.get(f"/ops/t/{A}/queue").status_code == 200
    ev = _events(app.state.database_url, "STAFF_ACCESS_CHANGED")[-1]
    assert ev == {"user_id": "u-spec-b", "old": [B], "new": [A, B]}
    r = adm.post("/ops/admin/users/u-client-a/access", data={"csrf": csrf_of(adm), "staff_tenants": [B]})
    assert r.status_code == 400                                       # client viewers cannot be widened


def test_users_page_lists_lock_state_and_unlock_works(seeded, app_factory):
    app = app_factory()
    c = TestClient(app)
    for _ in range(auth.MAX_ACCOUNT_FAILURES):
        c.post("/login", data={"email": "aud" + "itor@ops.example", "password": "wrong"})
    adm = login(TestClient(app), seeded, "u-admin")
    page = adm.get("/ops/admin/users").text
    row = page[page.index('data-user="u-aud"'):]
    assert "Locked" in row[:600]
    assert adm.post("/ops/admin/users/u-aud/unlock", data={"csrf": csrf_of(adm)}).status_code == 200
    assert _events(app.state.database_url, "USER_UNLOCKED")[-1] == {"user_id": "u-aud"}
    login(TestClient(app), seeded, "u-aud")


def test_cli_invite_admin_bootstraps_first_admin(db_url, capsys):
    import json
    from disputes import cli
    assert cli.main(["--database-url", db_url, "invite-admin", "--email", "first.admin@ops.example",
                     "--name", "First Admin (SYNTHETIC)"]) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["invite_path"].startswith("/invite/")
    with psycopg.connect(db_url) as c:
        assert c.execute("SELECT role FROM users WHERE user_id = %s", (out["user_id"],)).fetchone()[0] == "ADMIN"
