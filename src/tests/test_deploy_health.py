"""Deploy module: /healthz and /readyz against a real Postgres (synthetic, fresh DB per test)."""
from __future__ import annotations

import json

import psycopg
from fastapi.testclient import TestClient

from disputes.web.app import create_app
from disputes.web.health import expected_migrations, readiness


def client(url: str) -> TestClient:
    return TestClient(create_app(database_url=url))


def test_healthz_needs_no_database():
    r = client("postgresql://nobody@127.0.0.1:1/none").get("/healthz")
    assert r.status_code == 200 and r.json() == {"status": "ok"}
    assert r.headers["cache-control"] == "no-store"


def test_readyz_ready_on_migrated_db(db_url):
    r = client(db_url).get("/readyz")
    assert r.status_code == 200 and r.json() == {"status": "ready"}


def test_readyz_db_unreachable_is_503_without_details():
    url = "postgresql://someuser:hunter2-password@127.0.0.1:1/none"
    r = client(url).get("/readyz")
    assert r.status_code == 503
    assert r.json() == {"status": "not_ready", "reason": "database_unreachable"}
    assert "hunter2" not in r.text and "127.0.0.1" not in r.text


def test_readyz_unmigrated_db(db_url):
    # a brand-new empty database next to the migrated one
    admin = db_url.rsplit("/", 1)[0] + "/postgres"
    name = db_url.rsplit("/", 1)[1] + "_empty"
    with psycopg.connect(admin, autocommit=True) as a:
        a.execute(f'CREATE DATABASE "{name}"')
    try:
        ok, reason = readiness(db_url.rsplit("/", 1)[0] + "/" + name, environment="dev")
        assert (ok, reason) == (False, "migrations_not_applied")
    finally:
        with psycopg.connect(admin, autocommit=True) as a:
            a.execute(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)')


def test_readyz_pending_migration(db_url):
    newest = max(expected_migrations())
    with psycopg.connect(db_url, autocommit=True) as c:
        c.execute("DELETE FROM schema_migrations WHERE version = %s", (newest,))
    r = client(db_url).get("/readyz")
    assert r.status_code == 503 and r.json()["reason"] == "migrations_pending"


def test_readyz_demo_refuses_non_synthetic_mode_in_db(db_url, monkeypatch):
    with psycopg.connect(db_url, autocommit=True) as c:
        c.execute("INSERT INTO tenants (tenant_id, display_name, synthetic) VALUES ('ops','ops',true) "
                  "ON CONFLICT DO NOTHING")
        c.execute("INSERT INTO config_versions (tenant_id, key, value, version, changed_by, reason) "
                  "VALUES ('ops','mode',%s::jsonb,1,'test','direct DB write, bypassing the admin lock')",
                  (json.dumps("live"),))
    assert readiness(db_url, environment="dev") == (True, "ok")
    assert readiness(db_url, environment="demo") == (False, "mode_not_synthetic")


def test_readyz_demo_ok_with_synthetic_mode_row(db_url):
    with psycopg.connect(db_url, autocommit=True) as c:
        c.execute("INSERT INTO tenants (tenant_id, display_name, synthetic) VALUES ('ops','ops',true) "
                  "ON CONFLICT DO NOTHING")
        c.execute("INSERT INTO config_versions (tenant_id, key, value, version, changed_by, reason) "
                  "VALUES ('ops','mode',%s::jsonb,1,'test','synthetic mode row')", (json.dumps("synthetic"),))
    assert readiness(db_url, environment="demo") == (True, "ok")


def test_health_endpoints_are_unauthenticated_but_other_pages_are_not(db_url):
    c = client(db_url)
    assert c.get("/healthz", follow_redirects=False).status_code == 200
    assert c.get("/ops", follow_redirects=False).status_code == 303
