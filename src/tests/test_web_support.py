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
    email = next(u[1] for u in demo.USERS if u[0] == uid)
    r = client.post("/login", data={"email": email, "password": demo.DEMO_PASSWORD}, follow_redirects=False)
    assert r.status_code == 303, r.text
    r = client.post("/login/mfa", data={"code": auth.current_totp(secrets[uid])}, follow_redirects=False)
    assert r.status_code == 303, r.text
    return client


def csrf_of(client) -> str:
    """Read the CSRF token out of the signed session cookie (test helper)."""
    from itsdangerous import URLSafeSerializer
    tok = client.cookies.get(auth.SESSION_COOKIE)
    return URLSafeSerializer("test-secret", salt="disputes.session.v1").loads(tok)["csrf"]
