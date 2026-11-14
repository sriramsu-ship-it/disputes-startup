"""One-shot demo bootstrap (SYNTHETIC DATA ONLY). OWNER: deploy.

    python deploy/bootstrap.py          (in the image: python /app/deploy/bootstrap.py)

Idempotent; safe to run on every `docker compose up`:
  1. waits for Postgres (up to DISPUTES_BOOTSTRAP_WAIT_S, default 60 s);
  2. applies migrations (`disputes.cli migrate`);
  3. creates the synthetic tenants and demo users (`disputes.cli seed-demo`; existing users are
     left untouched, so their password does not change on re-runs);
  4. enqueues the committed synthetic fixture disputes for a tenant ONLY if that tenant has no jobs
     yet (set DISPUTES_DEMO_INGEST=0 to skip). The worker then processes them.

Prints which logins exist. The shared demo password is printed only when DISPUTES_ENV=dev (local
laptop), never in a hosted environment, and TOTP secrets are never printed (in local dev the MFA page
shows the current code when DISPUTES_DEV_SHOW_TOTP=1).
"""
from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

SRC = Path(os.environ.get("DISPUTES_SRC_DIR") or Path(__file__).resolve().parents[1] / "src")
if (SRC / "disputes").is_dir() and str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

import psycopg  # noqa: E402

from disputes import cli  # noqa: E402
from disputes.config import settings  # noqa: E402
from disputes.hosting import UnsafeHostedConfig, enforce_hosted_safety  # noqa: E402

FIXTURES = SRC / "data" / "fixtures"
# tenant -> committed synthetic fixture set
DEMO_INGEST = (("synthetic-tenant-0", "v1_seed20261107_n200"),
               ("synthetic-tenant-1", "seed20261019_n200"))


def wait_for_db(url: str, timeout_s: float) -> None:
    admin = cli._with_db(url, "postgres")
    deadline, last = time.monotonic() + timeout_s, None
    while time.monotonic() < deadline:
        try:
            psycopg.connect(admin, connect_timeout=3).close()
            return
        except psycopg.OperationalError as e:
            last = type(e).__name__
            time.sleep(1)
    raise SystemExit(f"bootstrap: database not reachable after {timeout_s:.0f}s ({last})")


def run(url: str, *, password: str | None, ingest: bool, env_name: str) -> dict:
    from disputes.db.core import connect, migrate
    created = cli._create_database(url)
    with connect(url) as c:
        applied = migrate(c)
        c.commit()
    out: dict = {"database_created": created, "migrations_applied": applied}
    with connect(url) as c:
        seeded = cli.seed_demo(c, password=password)
        users = c.execute("SELECT user_id, email, role, tenant_id FROM users ORDER BY role, user_id").fetchall()
    out["users_created_now"] = [u["user_id"] for u in seeded.get("users", [])]
    out["logins"] = [{"email": u["email"], "role": u["role"], "client": u["tenant_id"]} for u in users]
    if env_name == "dev":
        out["password"] = (seeded.get("password") if seeded.get("users")
                           else password or "(unchanged since first run; see the runbook to reset)")
    out["ingested"] = []
    if ingest:
        with connect(url) as c:
            for tenant_id, fixture in DEMO_INGEST:
                has = c.execute("SELECT 1 FROM jobs WHERE tenant_id = %s LIMIT 1", (tenant_id,)).fetchone()
                if has:
                    continue
                r = cli.ingest(c, tenant_id=tenant_id, fixtures_dir=FIXTURES / fixture, fixture_dates=True)
                out["ingested"].append({"tenant_id": tenant_id, "fixture": fixture, "enqueued": r["enqueued"]})
    return out


def main() -> int:
    try:
        enforce_hosted_safety()
    except UnsafeHostedConfig as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 2
    st = settings()
    wait_for_db(st.database_url, float(os.environ.get("DISPUTES_BOOTSTRAP_WAIT_S", "60")))
    out = run(st.database_url, password=os.environ.get("DISPUTES_DEMO_PASSWORD") or None,
              ingest=os.environ.get("DISPUTES_DEMO_INGEST", "1") != "0", env_name=st.environment)
    print(json.dumps(out, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
