import sys
from pathlib import Path

import pytest

SRC = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SRC))

from synthgen import generator  # noqa: E402

SEED = 20261019


@pytest.fixture(scope="session")
def batch():
    return generator.generate(SEED, 1000)


@pytest.fixture(scope="session")
def trial():
    return generator.generate_trial(SEED)


# ----------------------------------------------------------------- platform DB fixtures
# Each test that needs Postgres gets a fresh database cloned from a migrated template
# (fast, isolated, safe for parallel agents sharing one server).
import os  # noqa: E402
import subprocess  # noqa: E402
import uuid  # noqa: E402

import psycopg  # noqa: E402

ADMIN_URL = os.environ.get("DISPUTES_TEST_ADMIN_URL", "postgresql://postgres@127.0.0.1:5432/postgres")


def _admin():
    return psycopg.connect(ADMIN_URL, autocommit=True)


def _ensure_server():
    try:
        _admin().close()
        return
    except psycopg.OperationalError:
        script = SRC.parent / "scripts" / "dev_postgres.sh"
        subprocess.run(["bash", str(script), "start"], check=True)
        _admin().close()


def _url_for(dbname: str) -> str:
    return ADMIN_URL.rsplit("/", 1)[0] + "/" + dbname


@pytest.fixture(scope="session")
def db_template():
    """A migrated template database for this test session."""
    _ensure_server()
    from disputes.db.core import connect, migrate
    name = f"tmpl_{os.getpid()}_{uuid.uuid4().hex[:6]}"
    with _admin() as a:
        a.execute(f'CREATE DATABASE "{name}" ENCODING \'UTF8\' LC_COLLATE \'C\' LC_CTYPE \'C\' TEMPLATE template0')
    with connect(_url_for(name)) as c:
        migrate(c)
        c.commit()
    yield name
    with _admin() as a:
        a.execute(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)')


@pytest.fixture
def db_url(db_template):
    """URL of a fresh database for one test (cloned from the template)."""
    name = f"t_{uuid.uuid4().hex[:10]}"
    with _admin() as a:
        a.execute(f'CREATE DATABASE "{name}" TEMPLATE "{db_template}"')
    yield _url_for(name)
    with _admin() as a:
        a.execute(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)')


@pytest.fixture
def conn(db_url):
    from disputes.db.core import connect
    c = connect(db_url)
    yield c
    c.close()


@pytest.fixture
def tenant(conn):
    from disputes.db.core import ensure_tenant
    ensure_tenant(conn, "synthetic-tenant-0", "Example Fintech Lender (SYNTHETIC)")
    conn.commit()
    return "synthetic-tenant-0"
