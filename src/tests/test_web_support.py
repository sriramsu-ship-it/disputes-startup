"""Shared fixtures for the web tests (no tests here). Data is SYNTHETIC (disputes.web.demo)."""
from __future__ import annotations

import pytest

from disputes.contracts_bridge import StubResponseSink
from disputes.domain import Role
from disputes.web import auth, demo
from disputes.web.actions import Actor

A, B = demo.TENANT_A, demo.TENANT_B
NAMES = {u[0]: u[2] for u in demo.USERS}
ROLES = {u[0]: Role(u[3]) for u in demo.USERS}


def actor(uid: str) -> Actor:
    return Actor(uid, ROLES[uid], NAMES[uid])


@pytest.fixture
def seeded(conn):
    """Tenants A and B plus users of every role. Returns {user_id: totp_secret}. Committed."""
    secrets = demo.seed_users(conn)
    conn.commit()
    return secrets


@pytest.fixture
def sink():
    return StubResponseSink()


def case(conn, case_id: str, scenario: str, tenant: str = A, **kw) -> dict:
    row = demo.make_case(conn, tenant_id=tenant, case_id=case_id, scenario=scenario, **kw)
    conn.commit()
    return row


@pytest.fixture
def app_factory(db_url):
    from disputes.web.app import create_app

    def make(**kw):
        return create_app(database_url=db_url, session_secret="test-secret", **kw)
    return make


def login(client, secrets: dict, uid: str):
    """Password + TOTP. TOTP codes are single-use per 30 s step (replay protection), so the helper
    forgets the user's last accepted step first; tests may sign the same user in more than once."""
    import psycopg
    email = next(u[1] for u in demo.USERS if u[0] == uid)
    r = client.post("/login", data={"email": email, "password": demo.DEMO_PASSWORD}, follow_redirects=False)
    assert r.status_code == 303, r.text
    with psycopg.connect(client.app.state.database_url) as c:
        c.execute("UPDATE users SET totp_last_step = NULL WHERE user_id = %s", (uid,))
    r = client.post("/login/mfa", data={"code": auth.current_totp(secrets[uid])}, follow_redirects=False)
    assert r.status_code == 303, r.text
    return client


def csrf_of(client) -> str:
    """Read the CSRF token of the client's server-side session (test helper)."""
    import psycopg
    tok = client.cookies.get(client.app.state.session_cookie)
    with psycopg.connect(client.app.state.database_url) as c:
        row = c.execute("SELECT csrf FROM web_sessions WHERE session_hash = %s", (auth.token_hash(tok),)).fetchone()
    return row[0]
