"""Health endpoints and hosted-mode startup check. OWNER: deploy.

    GET /healthz  -> 200 {"status": "ok"}           process is up (no DB call; container/ECS liveness)
    GET /readyz   -> 200 {"status": "ready"}        DB reachable, every migration file applied, and
                                                    (DISPUTES_ENV=demo) the effective DB config mode
                                                    is still "synthetic"
                  -> 503 {"status": "not_ready", "reason": ...} otherwise (ALB target health)

Both are unauthenticated and return no configuration values, hostnames or error text (the
reason is a fixed code). The router's lifespan runs `hosting.enforce_hosted_safety()`, so
`uvicorn` refuses to start the app in an unsafe hosted configuration.
"""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager

import psycopg
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from starlette.concurrency import run_in_threadpool

from disputes.config import settings
from disputes.db.core import MIGRATIONS_DIR
from disputes.hosting import enforce_hosted_safety

log = logging.getLogger(__name__)
CONNECT_TIMEOUT_S = 3


@asynccontextmanager
async def _lifespan(app):
    enforce_hosted_safety()
    yield


router = APIRouter(lifespan=_lifespan)


def expected_migrations() -> set[str]:
    return {p.stem for p in MIGRATIONS_DIR.glob("*.sql")}


def readiness(database_url: str, *, environment: str) -> tuple[bool, str]:
    """(ready, reason_code). Never raises."""
    try:
        with psycopg.connect(database_url, connect_timeout=CONNECT_TIMEOUT_S, autocommit=True) as c:
            c.execute("SET statement_timeout = 3000")
            reg = c.execute("SELECT to_regclass('schema_migrations')").fetchone()[0]
            if reg is None:
                return False, "migrations_not_applied"
            done = {r[0] for r in c.execute("SELECT version FROM schema_migrations").fetchall()}
            if expected_migrations() - done:
                return False, "migrations_pending"
            if environment == "demo":
                row = c.execute("SELECT value FROM config_versions WHERE tenant_id = 'ops' AND key = 'mode' "
                                "ORDER BY version DESC LIMIT 1").fetchone()
                if row is not None and str(row[0]).strip('"') != "synthetic":
                    return False, "mode_not_synthetic"
    except psycopg.Error as e:
        log.warning("readyz: database check failed (%s)", type(e).__name__)
        return False, "database_unreachable"
    return True, "ok"


@router.get("/healthz", include_in_schema=False)
async def healthz():
    return JSONResponse({"status": "ok"}, headers={"Cache-Control": "no-store"})


@router.get("/readyz", include_in_schema=False)
async def readyz(request: Request):
    st = settings()
    url = getattr(request.app.state, "database_url", None) or st.database_url
    ok, reason = await run_in_threadpool(readiness, url, environment=st.environment)
    body = {"status": "ready"} if ok else {"status": "not_ready", "reason": reason}
    return JSONResponse(body, status_code=200 if ok else 503, headers={"Cache-Control": "no-store"})
