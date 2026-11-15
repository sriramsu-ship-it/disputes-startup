"""Hardening: attacker self-review. One test per attempt: CSRF (token and cross-site origin, login
CSRF), forced browsing per role, IDOR across tenants (staff and client), stored XSS via letter
text / narrative / user names, security headers, body limits, no stack traces, masked request log.
(Session fixation and replay are in test_hardening_auth.py.) SYNTHETIC data only."""
from __future__ import annotations

import json
import logging
import re
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from disputes.web import admin_users, demo
from test_web_support import A, B, actor, app_factory, case, csrf_of, login, seeded  # noqa: F401

XSS = '<script>alert("x")</script><img src=x onerror=alert(1)>'
TEMPLATES = Path(__file__).resolve().parents[1] / "disputes" / "web" / "templates"


# ------------------------------------------------------------------ CSRF
def test_csrf_missing_or_forged_token_is_refused(conn, seeded, app_factory):
    case(conn, "X1", "verify")
    c = login(TestClient(app_factory()), seeded, "u-spec")
    c.get(f"/ops/t/{A}/cases/X1")
    assert c.post(f"/ops/t/{A}/cases/X1/actions/approve", data={}).status_code == 403
    other = login(TestClient(app_factory()), seeded, "u-sup1")                 # someone else's valid token
    assert c.post(f"/ops/t/{A}/cases/X1/actions/approve", data={"csrf": csrf_of(other)}).status_code == 403
    assert conn.execute("SELECT state FROM cases WHERE case_id='X1'").fetchone()["state"] == "IN_REVIEW"


def test_cross_site_post_is_refused_even_with_a_valid_token(conn, seeded, app_factory):
    case(conn, "X2", "verify")
    c = login(TestClient(app_factory()), seeded, "u-spec")
    c.get(f"/ops/t/{A}/cases/X2")
    tok = csrf_of(c)
    for h in ({"Origin": "https://evil.example"}, {"Sec-Fetch-Site": "cross-site"}, {"Origin": "null"}):
        r = c.post(f"/ops/t/{A}/cases/X2/actions/approve", data={"csrf": tok}, headers=h)
        assert r.status_code == 403, h
    assert conn.execute("SELECT state FROM cases WHERE case_id='X2'").fetchone()["state"] == "IN_REVIEW"
    r = c.post(f"/ops/t/{A}/cases/X2/actions/approve", data={"csrf": tok},
               headers={"Origin": "http://testserver", "Sec-Fetch-Site": "same-origin"}, follow_redirects=False)
    assert r.status_code == 303


def test_login_csrf_from_another_site_is_refused(seeded, app_factory):
    c = TestClient(app_factory())
    r = c.post("/login", data={"email": "spec@ops.example", "password": demo.DEMO_PASSWORD},
               headers={"Origin": "https://evil.example"}, follow_redirects=False)
    assert r.status_code == 403 and "disputes_mfa_pending" not in r.headers.get("set-cookie", "")
    r = c.post("/login/mfa", data={"code": "123456"}, headers={"Sec-Fetch-Site": "cross-site"})
    assert r.status_code == 403


# ------------------------------------------------------------------ forced browsing per role
MATRIX = {
    # path: {uid or None (anonymous): expected status}
    "/ops/admin": {"u-admin": 200, "u-sup1": 403, "u-spec": 403, "u-aud": 403, "u-client-a": 403, None: 303},
    "/ops/admin/users": {"u-admin": 200, "u-sup1": 403, "u-spec": 403, "u-aud": 403, "u-client-a": 403, None: 303},
    f"/ops/t/{A}/metrics.csv": {"u-admin": 200, "u-sup1": 200, "u-spec": 403, "u-aud": 403, "u-client-a": 403,
                                None: 303},
    f"/ops/t/{A}/queue": {"u-admin": 200, "u-sup1": 200, "u-spec": 200, "u-aud": 200, "u-spec-b": 404,
                          "u-client-a": 403, None: 303},
    "/ops/t/ops/queue": {"u-admin": 404, "u-spec": 404},
    "/client": {"u-client-a": 200, "u-admin": 403, "u-spec": 403, None: 303},
    "/healthz": {None: 200},
    "/docs": {None: 404}, "/openapi.json": {None: 404}, "/redoc": {None: 404},
}


def test_forced_browsing_matrix(seeded, app_factory):
    app = app_factory()
    clients = {None: TestClient(app)}
    got = {}
    for path, expect in MATRIX.items():
        for uid, status in expect.items():
            if uid not in clients:
                clients[uid] = login(TestClient(app), seeded, uid)
            got[(path, uid)] = clients[uid].get(path, follow_redirects=False).status_code
    want = {(p, u): s for p, e in MATRIX.items() for u, s in e.items()}
    assert got == want


def test_read_only_staff_cannot_act(conn, seeded, app_factory):
    case(conn, "X3", "verify")
    aud = login(TestClient(app_factory()), seeded, "u-aud")
    aud.get(f"/ops/t/{A}/cases/X3")
    for action in ("approve", "edit", "escalate", "take", "reopen", "out_of_scope"):
        assert aud.post(f"/ops/t/{A}/cases/X3/actions/{action}",
                        data={"csrf": csrf_of(aud), "reason_text": "auditor trying to act"}).status_code in (400, 403)
    assert conn.execute("SELECT state FROM cases WHERE case_id='X3'").fetchone()["state"] == "DRAFT_READY"


# ------------------------------------------------------------------ IDOR across tenants
def test_staff_idor_on_every_case_route(conn, seeded, app_factory):
    case(conn, "XA", "submitted")
    c = login(TestClient(app_factory()), seeded, "u-spec-b")           # assigned to B only
    tok = csrf_of(c)
    before = conn.execute("SELECT count(*) AS n FROM case_metrics WHERE case_id='XA'").fetchone()["n"]
    for path in (f"/ops/t/{A}/cases/XA", f"/ops/t/{A}/cases/XA/export.json", f"/ops/t/{B}/cases/XA",
                 f"/ops/t/{B}/cases/XA/export.json", f"/ops/t/{B}/cases/XA/export.html"):
        assert c.get(path).status_code == 404, path
    assert c.post(f"/ops/t/{B}/cases/XA/actions/reopen", data={"csrf": tok}).status_code == 404
    assert c.post(f"/ops/t/{B}/cases/XA/metrics", json={"csrf": tok, "active_seconds": 5}).status_code == 404
    conn.rollback()
    assert conn.execute("SELECT count(*) AS n FROM case_metrics WHERE case_id='XA'").fetchone()["n"] == before
    assert conn.execute("SELECT state FROM cases WHERE case_id='XA'").fetchone()["state"] == "SUBMITTED_STUB"


def test_client_idor_by_guessing_case_ids(conn, seeded, app_factory):
    case(conn, "XB", "submitted", tenant=B)
    c = login(TestClient(app_factory()), seeded, "u-client-a")
    for path in ("/client/cases/XB", "/client/cases/XB/export.json", "/client/cases/XB/export.html",
                 f"/ops/t/{B}/cases/XB", f"/ops/t/{B}/cases/XB/export.json"):
        assert c.get(path).status_code in (403, 404), path
    assert "XB" not in c.get("/client").text


# ------------------------------------------------------------------ stored XSS
def test_stored_xss_in_letter_narrative_and_names_is_escaped_everywhere(conn, seeded, app_factory):
    case(conn, "XS", "verify")
    conn.execute("UPDATE attachments SET extracted_text = extracted_text || %s WHERE case_id = 'XS'", ("\n" + XSS,))
    conn.commit()
    spec = actor("u-spec")
    from disputes.web import actions as act
    act.open_case(conn, tenant_id=A, case_id="XS", actor=spec)
    act.edit(conn, tenant_id=A, case_id="XS", actor=spec, reason_code="NARRATIVE_EDIT_ONLY",
             reason_text="narrative with markup " + XSS, narrative="We checked. " + XSS)
    conn.commit()
    admin_users.create_user(conn, actor_id="u-admin", actor_role="ADMIN", email="xss@ops.example",
                            display_name=XSS[:90], role="SPECIALIST", client_tenant=None, staff_tenants=[A])
    conn.commit()
    app = app_factory()
    staff = login(TestClient(app), seeded, "u-spec")
    adm = login(TestClient(app), seeded, "u-admin")
    pages = [staff.get(f"/ops/t/{A}/cases/XS").text, staff.get(f"/ops/t/{A}/cases/XS/export.html").text,
             adm.get("/ops/admin/users").text]
    for html in pages:
        assert "<script>alert" not in html and "<img src=x onerror" not in html
        assert "&lt;script&gt;" in html
    j = staff.get(f"/ops/t/{A}/cases/XS/export.json")
    assert j.headers["content-type"].startswith("application/json")


def test_templates_have_no_inline_script_style_or_handlers():
    for f in TEMPLATES.rglob("*.html"):
        t = f.read_text(encoding="utf-8")
        assert not re.search(r"<script(?![^>]*\bsrc=)[^>]*>", t), f.name
        assert not re.search(r"\sstyle\s*=", t), f.name
        assert not re.search(r"\son[a-z]+\s*=", t), f.name
        assert "|safe" not in t.replace(" ", ""), f.name


# ------------------------------------------------------------------ headers, limits, errors, logs
def test_security_headers(seeded, app_factory):
    r = TestClient(app_factory()).get("/login")
    h = r.headers
    csp = h["content-security-policy"]
    for part in ("default-src 'self'", "script-src 'self'", "frame-ancestors 'none'", "base-uri 'none'",
                 "object-src 'none'", "form-action 'self'"):
        assert part in csp
    assert "unsafe-inline" not in csp and "unsafe-eval" not in csp
    assert h["x-frame-options"] == "DENY" and h["x-content-type-options"] == "nosniff"
    assert h["referrer-policy"] == "same-origin" and h["cache-control"] == "no-store"
    assert h["cross-origin-opener-policy"] == "same-origin" and "x-request-id" in h
    assert "server" not in {k.lower() for k in h if h[k].lower().startswith("uvicorn")}


def test_body_size_limit(seeded, app_factory, monkeypatch):
    monkeypatch.setenv("DISPUTES_MAX_BODY_BYTES", "4096")
    c = TestClient(app_factory())
    r = c.post("/login", content=b"email=a&password=" + b"x" * 5000,
               headers={"content-type": "application/x-www-form-urlencoded"})
    assert r.status_code == 413

    def chunks():
        for _ in range(10):
            yield b"x" * 1000
    r = c.post("/login", content=chunks(), headers={"content-type": "application/x-www-form-urlencoded"})
    assert r.status_code == 413
    assert c.post("/login", data={"email": "a@b.example", "password": "y"}).status_code == 401


def test_no_stack_trace_to_client_and_masked_log(seeded, app_factory, caplog):
    app = app_factory()

    @app.get("/boom-test-only")
    async def boom():
        raise ValueError("lookup failed for SYNACCT3810123213 ssn 905-00-2979")
    c = TestClient(app, raise_server_exceptions=False)
    with caplog.at_level(logging.INFO, logger="disputes.web.request"):
        r = c.get("/boom-test-only")
    assert r.status_code == 500
    assert "Traceback" not in r.text and "ValueError" not in r.text and "SYNACCT" not in r.text
    rid = r.headers["x-request-id"]
    assert rid in r.text and r.headers["content-security-policy"]
    logged = [json.loads(x.getMessage()) for x in caplog.records if x.name == "disputes.web.request"]
    err = [x for x in logged if x["event"] == "unhandled_error"][0]
    assert err["request_id"] == rid and "3810123213" not in err["error"] and "905-00" not in err["error"]
    assert any(x["event"] == "http_request" and x["status"] == 500 for x in logged)


def test_request_log_redacts_invite_tokens(conn, seeded, app_factory, caplog):
    out = admin_users.create_user(conn, actor_id="u-admin", actor_role="ADMIN", email="tok@ops.example",
                                  display_name="Tok", role="SPECIALIST", client_tenant=None, staff_tenants=[])
    conn.commit()
    token = out["invite_path"].rsplit("/", 1)[1]
    with caplog.at_level(logging.INFO, logger="disputes.web.request"):
        TestClient(app_factory()).get(out["invite_path"])
    text = " ".join(x.getMessage() for x in caplog.records)
    assert token not in text and "/invite/<redacted>" in text


@pytest.mark.parametrize("path", ["/login", "/login/mfa", "/invite/abc"])
def test_auth_pages_are_not_cached(seeded, app_factory, path):
    r = TestClient(app_factory()).get(path, follow_redirects=False)
    assert r.headers.get("cache-control") == "no-store" or r.status_code == 303
