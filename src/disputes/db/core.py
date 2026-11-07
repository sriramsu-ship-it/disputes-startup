"""Database access: connections, migrations, tenant scoping (ADR-001, ADR-008).

Rules for every module:
- Use `connect()` / `transaction()`; never build your own connection string.
- Every SQL statement that reads or writes a tenant-owned table includes `tenant_id` in its
  WHERE clause or VALUES (tests/test_tenant_scoping.py enforces this for disputes/db/repo.py).
- Migrations live in disputes/db/migrations/NNNN_<module>_<name>.sql and are applied in
  filename order. Number ranges per module (to avoid clashes between parallel agents):
    0001        foundation
    0002-0009   audit / workflow (platform-core)
    0010-0019   web
    0020-0029   rules / intake / agents (if ever needed)
"""
from __future__ import annotations

import contextlib
from pathlib import Path
from typing import Iterator

import psycopg
from psycopg.rows import dict_row

from disputes.config import settings

MIGRATIONS_DIR = Path(__file__).parent / "migrations"


def connect(database_url: str | None = None) -> psycopg.Connection:
    """A new connection with dict rows. Caller owns it (use as a context manager)."""
    return psycopg.connect(database_url or settings().database_url, row_factory=dict_row)


@contextlib.contextmanager
def transaction(conn: psycopg.Connection) -> Iterator[psycopg.Connection]:
    """Commit on success, roll back on error. Nests as a savepoint inside an open transaction."""
    with conn.transaction():
        yield conn


def migrate(conn: psycopg.Connection) -> list[str]:
    """Apply pending migrations in filename order. Returns the versions applied."""
    conn.execute("CREATE TABLE IF NOT EXISTS schema_migrations (version text PRIMARY KEY, "
                 "applied_at timestamptz NOT NULL DEFAULT now())")
    conn.commit()
    done = {r["version"] for r in conn.execute("SELECT version FROM schema_migrations").fetchall()}
    applied = []
    for path in sorted(MIGRATIONS_DIR.glob("*.sql")):
        version = path.stem
        if version in done:
            continue
        with conn.transaction():
            conn.execute(path.read_text(encoding="utf-8"))
            conn.execute("INSERT INTO schema_migrations (version) VALUES (%s)", (version,))
        applied.append(version)
    return applied


def ensure_tenant(conn: psycopg.Connection, tenant_id: str, display_name: str, synthetic: bool = True) -> None:
    conn.execute(
        "INSERT INTO tenants (tenant_id, display_name, synthetic) VALUES (%s, %s, %s) "
        "ON CONFLICT (tenant_id) DO NOTHING", (tenant_id, display_name, synthetic))
