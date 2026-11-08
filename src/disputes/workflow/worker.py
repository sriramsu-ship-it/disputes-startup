"""Worker: drains `process_dispute` jobs with the pipeline (ADR-002). OWNER: platform-core.

Job payload (written by `disputes.cli ingest`):
    {"envelope": <fixture ACDV envelope>, "sor_path": "<abs path to the tenant's sor_accounts.jsonl>",
     "as_of": "<optional ISO datetime used as the pipeline's `now` for replaying fixtures>"}

Failure handling:
- the pipeline escalates its own failures (fail safe) and returns normally;
- an exception that escapes it (DB failure while escalating) -> the case, if one exists and is
  still pre-review, is escalated via `pipeline.escalate_stuck_case`, and the job is failed with
  backoff; after max_attempts the job is dead-lettered (jobs.fail escalates and audits);
- a payload that cannot be mapped or is refused (unsupported schema version, non-synthetic in
  synthetic mode, tenant mismatch) is dead-lettered at once (retrying cannot help).
Known gap (ADR-002 deviation): job completion commits after the pipeline's last step, not in
the same transaction. A crash in between re-runs the job, which then logs DUPLICATE_IGNORED
against the already-finished case (harmless, visible in the audit log).
"""
from __future__ import annotations

import logging
import time
from datetime import datetime, timezone
from functools import lru_cache
from typing import Callable

import psycopg

from disputes.config import Config
from disputes.workflow import jobs
from disputes.workflow.pipeline import NonSyntheticRefused, escalate_stuck_case, process_dispute

log = logging.getLogger(__name__)
KIND = "process_dispute"


@lru_cache(maxsize=32)
def _sor(path: str):
    from disputes.contracts_bridge import MockSystemOfRecord
    return MockSystemOfRecord(path)


def default_deps_for(cfg: Config, backend: str | None = None) -> Callable:
    """deps_for(tenant_id, payload) -> Deps using the real modules and the payload's SoR file."""
    from disputes.config import settings
    from disputes.workflow.pipeline import default_deps
    client_box: dict = {}

    def deps_for(tenant_id: str, payload: dict):
        if "client" not in client_box:
            from disputes.agents.llm import make_client
            client_box["client"] = make_client(backend or settings().llm_backend, cfg)
        return default_deps(_sor(payload["sor_path"]), client_box["client"], cfg)
    return deps_for


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _as_of(payload: dict, now_fn) -> datetime:
    s = payload.get("as_of") if isinstance(payload, dict) else None
    if s:
        dt = datetime.fromisoformat(s)
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    return now_fn()


def _idle(conn) -> None:
    if conn.info.transaction_status != psycopg.pq.TransactionStatus.IDLE:
        conn.rollback()


def process_one(conn, job: dict, *, deps_for: Callable, cfg: Config, now_fn=_utcnow,
                backoff_base_s: float = jobs.DEFAULT_BACKOFF_BASE_S) -> str:
    """Run one claimed job. Returns 'done' | 'retry' | 'dead' | 'lost'."""
    from disputes.contracts_bridge import acdv_to_dispute
    from disputes_core.contracts import UnsupportedSchemaVersion
    tenant_id, payload = job["tenant_id"], job["payload"]
    try:
        dispute = acdv_to_dispute(payload["envelope"], tenant_id=tenant_id)
        deps = deps_for(tenant_id, payload)
        now = _as_of(payload, now_fn)
    except (UnsupportedSchemaVersion, KeyError, TypeError, ValueError) as e:
        _idle(conn)
        st = jobs.fail(conn, job, error=f"unprocessable payload: {type(e).__name__}: {e}", retryable=False)
        return "dead" if st == "DEAD" else "lost"
    try:
        res = process_dispute(conn, tenant_id=tenant_id, dispute=dispute, deps=deps, cfg=cfg, now=now)
    except (NonSyntheticRefused, ValueError) as e:
        _idle(conn)
        st = jobs.fail(conn, job, error=f"refused: {type(e).__name__}: {e}", retryable=False)
        return "dead" if st == "DEAD" else "lost"
    except Exception as e:  # noqa: BLE001 - fail safe
        _idle(conn)
        err = f"{type(e).__name__}: {e}"
        log.error("job %s failed: %s", job["job_id"], type(e).__name__)
        case_id = None
        try:
            case_id = escalate_stuck_case(conn, tenant_id=tenant_id, control_number=dispute.control_number,
                                          error=err)
        except Exception:  # noqa: BLE001 - DB still failing; the retry/dead-letter path covers it
            _idle(conn)
        st = jobs.fail(conn, job, error=err, backoff_base_s=backoff_base_s, case_id=case_id)
        return {"QUEUED": "retry", "DEAD": "dead"}.get(st, "lost")
    return "done" if jobs.complete(conn, job, case_id=res.case_id) else "lost"


def run_worker(conn, *, cfg: Config, deps_for: Callable | None = None, tenant_ids: list[str] | None = None,
               max_jobs: int | None = None, lease_s: float = jobs.DEFAULT_LEASE_S,
               backoff_base_s: float = jobs.DEFAULT_BACKOFF_BASE_S, wait_for_backoff: bool = False,
               max_wait_s: float = 120.0, now_fn=_utcnow) -> dict:
    """Drain claimable jobs. With wait_for_backoff, also waits (up to max_wait_s in total) for
    jobs in backoff, so the queue is empty when it returns. Returns counts."""
    deps_for = deps_for or default_deps_for(cfg)
    stats = {"done": 0, "retry": 0, "dead": 0, "lost": 0, "reaped": 0}
    waited = 0.0
    _idle(conn)
    while max_jobs is None or sum(stats[k] for k in ("done", "retry", "dead", "lost")) < max_jobs:
        r = jobs.reap_expired_leases(conn, tenant_ids=tenant_ids)
        stats["reaped"] += r["requeued"] + r["dead"]
        stats["dead"] += r["dead"]
        job = jobs.claim(conn, kinds=(KIND,), tenant_ids=tenant_ids, lease_s=lease_s)
        if job is None:
            nxt = jobs.next_run_after_s(conn, kinds=(KIND,), tenant_ids=tenant_ids)
            if not wait_for_backoff or nxt is None or waited >= max_wait_s:
                break
            pause = min(max(nxt, 0.05), 1.0, max_wait_s - waited)
            time.sleep(pause)
            waited += pause
            continue
        stats[process_one(conn, job, deps_for=deps_for, cfg=cfg, now_fn=now_fn,
                          backoff_base_s=backoff_base_s)] += 1
    stats["queue"] = jobs.counts(conn, tenant_ids=tenant_ids)
    return stats
