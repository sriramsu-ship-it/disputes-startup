"""R-18 auth (passwords, TOTP, sessions, roles, tenant access) and R-27 log masking."""
from __future__ import annotations

import logging
import time

import pytest
from fastapi.testclient import TestClient

from disputes.web import auth, demo
from disputes.web.pii import PiiMaskingFilter, mask_account, mask_text
from test_web_support import A, B, app_factory, case, csrf_of, login, seeded  # noqa: F401


# ------------------------------------------------------------------ unit
def test_password_hash_roundtrip_and_salting():
    h1, h2 = auth.hash_password("correct horse"), auth.hash_password("correct horse")
    assert h1 != h2 and h1.startswith("scrypt$")
    assert auth.verify_password("correct horse", h1)
    assert not auth.verify_password("wrong", h1)
    assert not auth.verify_password("x", "not-a-hash") and not auth.verify_password("x", "md5$1$2$3$aa$bb")
    with pytest.raises(ValueError):
        auth.hash_password("")


def test_seed_demo_contract_signatures():
    """platform-core `cli seed-demo` calls these by name: hash_password(pw) -> str, new_totp_secret() -> str."""
    assert isinstance(auth.hash_password("pw"), str)
    s = auth.new_totp_secret()
    assert isinstance(s, str) and len(s) >= 16


def test_totp_verification():
    s = auth.new_totp_secret()
    now = time.time()
    assert auth.verify_totp(s, auth.current_totp(s, at=now), at=now)
    assert auth.verify_totp(s, auth.current_totp(s, at=now - 30), at=now)      # one step of drift
    assert not auth.verify_totp(s, auth.current_totp(s, at=now - 300), at=now)
    assert not auth.verify_totp(s, "abcdef") and not auth.verify_totp(None, "123456") and not auth.verify_totp(s, "")


def test_session_idle_timeout_and_tamper():
    c = auth.SessionCodec("k")
    sess = c.new_session("u1", now=1000)
    tok = c.dump(sess)
    assert c.load(tok, idle_timeout_s=1800, now=1000 + 1799)["uid"] == "u1"
    assert c.load(tok, idle_timeout_s=1800, now=1000 + 1801) is None
    assert c.load(tok + "x", idle_timeout_s=1800, now=1001) is None
    assert auth.SessionCodec("other").load(tok, idle_timeout_s=1800, now=1001) is None
    touched = c.dump(c.touch(sess, now=2500))
    assert c.load(touched, idle_timeout_s=1800, now=4000) is not None          # activity extends it


def test_tenant_access_by_role(conn, seeded):
    p = lambda uid: auth.load_principal(conn, uid)  # noqa: E731
    assert auth.tenant_ids_for(conn, p("u-admin")) == [A, B]
    assert auth.tenant_ids_for(conn, p("u-spec")) == [A, B]
    assert auth.tenant_ids_for(conn, p("u-spec-b")) == [B]
    assert auth.tenant_ids_for(conn, p("u-client-a")) == [A]
    assert not auth.staff_can_access_tenant(conn, p("u-client-a"), A)       # clients never get /ops
    conn.execute("UPDATE users SET active = false WHERE user_id = 'u-spec'")
    assert auth.load_principal(conn, "u-spec") is None


def test_pii_masking_in_logs(caplog):
    assert mask_account("SYNACCT3810123213") == "••••3213"
    out = mask_text("acct SYNACCT3810123213 ssn 905-00-2979 card 4111111111111111 for Rowan Testcombe",
                    names=["Rowan Testcombe"])
    assert "3810123213" not in out and "905-00" not in out and "41111111" not in out and "Testcombe" not in out
    assert "••••3213" in out and "2979" in out and "R. T." in out
    lg = logging.getLogger("disputes.test_web_mask")
    lg.addFilter(PiiMaskingFilter())
    with caplog.at_level(logging.INFO, logger="disputes.test_web_mask"):
        lg.info("approved %s for ssn %s", "SYNACCT3810123213", "905002979", extra={"pii_names": ["Rowan"]})
    msg = caplog.records[-1].getMessage()
    assert "SYNACCT381" not in msg and "905002979" not in msg and "3213" in msg


# ------------------------------------------------------------------ HTTP login + MFA
def test_login_requires_password_then_totp(seeded, app_factory):
    c = TestClient(app_factory())
    assert c.get("/ops", follow_redirects=False).headers["location"] == "/login"
    r = c.post("/login", data={"email": "spec@ops.example", "password": "wrong"}, follow_redirects=False)
    assert r.status_code == 401 and "incorrect" in r.text
    r = c.post("/login", data={"email": "nobody@ops.example", "password": "x"}, follow_redirects=False)
    assert r.status_code == 401
    r = c.post("/login", data={"email": "spec@ops.example", "password": demo.DEMO_PASSWORD}, follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "/login/mfa"
    assert c.get("/ops", follow_redirects=False).status_code == 303            # password alone is not a session
    r = c.post("/login/mfa", data={"code": "000000"}, follow_redirects=False)
    assert r.status_code == 401
    r = c.post("/login/mfa", data={"code": auth.current_totp(seeded["u-spec"])}, follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "/ops"
    assert c.get("/ops/t/synthetic-tenant-0/queue").status_code == 200


def test_mfa_without_pending_password_step_is_refused(seeded, app_factory):
    c = TestClient(app_factory())
    r = c.post("/login/mfa", data={"code": auth.current_totp(seeded["u-spec"])}, follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "/login"


def test_user_without_totp_cannot_sign_in(conn, seeded, app_factory):
    conn.execute("UPDATE users SET totp_secret = NULL WHERE user_id = 'u-spec'")
    conn.commit()
    c = TestClient(app_factory())
    c.post("/login", data={"email": "spec@ops.example", "password": demo.DEMO_PASSWORD})
    r = c.get("/login/mfa")
    assert "no authenticator" in r.text
    assert c.post("/login/mfa", data={"code": "123456"}, follow_redirects=False).status_code == 401


def test_idle_timeout_logs_out(conn, seeded, app_factory):
    c = login(TestClient(app_factory()), seeded, "u-spec")
    codec = auth.SessionCodec("test-secret")
    old = codec.dump({"uid": "u-spec", "csrf": "x", "iat": 0, "seen": int(time.time()) - 31 * 60})
    c.cookies.clear()
    c.cookies.set(auth.SESSION_COOKIE, old)
    r = c.get("/ops/t/synthetic-tenant-0/queue", follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "/login"
    # the timeout is config: lower it to 1 minute and a 2-minute-old session is refused
    conn.execute("INSERT INTO config_versions (tenant_id, key, value, version, changed_by, reason) "
                 "VALUES ('ops','session_idle_timeout_min','1'::jsonb,1,'u-admin','test lower timeout')")
    conn.commit()
    c.cookies.clear()
    c.cookies.set(auth.SESSION_COOKIE, codec.dump({"uid": "u-spec", "csrf": "x", "iat": 0,
                                                   "seen": int(time.time()) - 120}))
    assert c.get("/ops", follow_redirects=False).headers["location"] == "/login"


def test_dev_totp_display_only_in_synthetic_mode_with_flag(seeded, app_factory, monkeypatch):
    def mfa_page(**kw):
        c = TestClient(app_factory(**kw))
        c.post("/login", data={"email": "spec@ops.example", "password": demo.DEMO_PASSWORD})
        return c.get("/login/mfa").text
    monkeypatch.delenv("DISPUTES_DEV_SHOW_TOTP", raising=False)
    assert 'data-testid="dev-totp"' not in mfa_page()
    monkeypatch.setenv("DISPUTES_DEV_SHOW_TOTP", "1")
    assert 'data-testid="dev-totp"' in mfa_page()
    assert 'data-testid="dev-totp"' not in mfa_page(mode="live")


def test_role_and_tenant_checks_on_server(seeded, app_factory):
    app = app_factory()
    client = login(TestClient(app), seeded, "u-client-a")
    assert client.get("/ops/t/synthetic-tenant-0/queue").status_code == 403
    assert client.get("/ops/admin").status_code == 403
    spec = login(TestClient(app), seeded, "u-spec")
    assert spec.get("/client").status_code == 403
    assert spec.get("/ops/admin").status_code == 403
    assert spec.get("/ops/t/synthetic-tenant-0/metrics.csv").status_code == 403
    specb = login(TestClient(app), seeded, "u-spec-b")
    assert specb.get("/ops/t/synthetic-tenant-0/queue").status_code == 404
    assert specb.get("/ops/t/synthetic-tenant-1/queue").status_code == 200
    assert specb.get("/ops/t/ops/queue").status_code == 404


def test_post_without_csrf_is_refused(conn, seeded, app_factory):
    case(conn, "C1", "verify")
    c = login(TestClient(app_factory()), seeded, "u-spec")
    c.get("/ops/t/synthetic-tenant-0/cases/C1")
    r = c.post("/ops/t/synthetic-tenant-0/cases/C1/actions/approve", data={})
    assert r.status_code == 403
    r = c.post("/ops/t/synthetic-tenant-0/cases/C1/actions/approve", data={"csrf": "forged"})
    assert r.status_code == 403
    assert conn.execute("SELECT state FROM cases WHERE case_id='C1'").fetchone()["state"] == "IN_REVIEW"
    r = c.post("/ops/t/synthetic-tenant-0/cases/C1/actions/approve", data={"csrf": csrf_of(c)},
               follow_redirects=False)
    assert r.status_code == 303


def test_logout_clears_session_and_cookie_flags(seeded, app_factory):
    c = TestClient(app_factory())
    c.post("/login", data={"email": "spec@ops.example", "password": demo.DEMO_PASSWORD})
    r = c.post("/login/mfa", data={"code": auth.current_totp(seeded["u-spec"])}, follow_redirects=False)
    sc = r.headers["set-cookie"].lower()
    assert "httponly" in sc and "samesite=lax" in sc
    c.post("/logout")
    assert c.get("/ops", follow_redirects=False).headers["location"] == "/login"
