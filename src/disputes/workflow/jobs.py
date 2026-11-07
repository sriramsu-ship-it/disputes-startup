"""Postgres job queue (ADR-002). OWNER: platform-core.

- `enqueue`: insert a QUEUED job for a tenant.
- `claim`: one job, `FOR UPDATE SKIP LOCKED`, status RUNNING, attempts+1, lease `locked_until`.
- `complete`: DONE (only if this claim still holds the lease: status RUNNING and same attempt).
- `fail`: back to QUEUED with exponential backoff (`backoff_base_s * 2**(attempts-1)`), or
  DEAD after `max_attempts` (or at once when `retryable=False`).
- dead letter = fail safe: the job's case (by case_id, else by the payload's control number) is
  moved to ESCALATED through the state machine, and a JOB_DEAD_LETTERED audit event is written
  in the same transaction. A dead job whose dispute never became a case still gets the audit
  event (case_id NULL) so ops can see it.
- `reap_expired_leases`: RUNNING jobs whose lease expired go back to QUEUED (or DEAD).

Every statement carries tenant_id except `claim`/`reap` across tenants, which are platform
operations by design (a worker serves all client tenants unless `tenant_ids` is given).
"""
from __future__ import annotations

from disputes.audit.chain import append_event, canonical
from disputes.db import repo
from disputes.domain import ActorType, CaseState
from disputes.workflow import state_machine

DEFAULT_LEASE_S = 300
DEFAULT_BACKOFF_BASE_S = 5.0
WORKER_ACTOR = "system:worker"


def enqueue(conn, *, tenant_id: str, kind: str, payload: dict, case_id: str | None = None,
            max_attempts: int = 3) -> int:
    with conn.transaction():
        return conn.execute(
            "INSERT INTO jobs (tenant_id, case_id, kind, payload, max_attempts) VALUES (%s,%s,%s,%s::jsonb,%s) "
            "RETURNING job_id", (tenant_id, case_id, kind, canonical(payload), max_attempts)).fetchone()["job_id"]


def claim(conn, *, kinds: tuple[str, ...] = ("process_dispute",), tenant_ids: list[str] | None = None,
          lease_s: float = DEFAULT_LEASE_S) -> dict | None:
    """Claim the oldest ready job. Commits immediately so the lease is visible to other workers."""
    where = ["status = 'QUEUED'", "run_after <= now()", "kind = ANY(%s)"]
    params: list = [list(kinds)]
    if tenant_ids is not None:
        where.append("tenant_id = ANY(%s)")
        params.append(list(tenant_ids))
    with conn.transaction():
        return conn.execute(
            "UPDATE jobs SET status = 'RUNNING', attempts = attempts + 1, "
            "locked_until = now() + make_interval(secs => %s), updated_at = now() "
            f"WHERE job_id = (SELECT job_id FROM jobs WHERE {' AND '.join(where)} "
            "ORDER BY run_after, job_id FOR UPDATE SKIP LOCKED LIMIT 1) RETURNING *",
            [lease_s, *params]).fetchone()


def _holds_lease(job: dict) -> tuple[str, list]:
    return ("tenant_id = %s AND job_id = %s AND status = 'RUNNING' AND attempts = %s",
            [job["tenant_id"], job["job_id"], job["attempts"]])


def complete(conn, job: dict, *, case_id: str | None = None) -> bool:
    """Mark DONE. Returns False if the lease was lost (reaped and re-claimed meanwhile)."""
    cond, params = _holds_lease(job)
    with conn.transaction():
        row = conn.execute(
            "UPDATE jobs SET status = 'DONE', locked_until = NULL, updated_at = now(), "
            f"case_id = COALESCE(%s, case_id) WHERE {cond} RETURNING job_id", [case_id, *params]).fetchone()
    return row is not None


def fail(conn, job: dict, *, error: str, retryable: bool = True,
         backoff_base_s: float = DEFAULT_BACKOFF_BASE_S, case_id: str | None = None) -> str | None:
    """Record a failure. Returns the new status ('QUEUED' or 'DEAD'), or None if the lease was lost."""
    cond, params = _holds_lease(job)
    with conn.transaction():
        cur = conn.execute(f"SELECT * FROM jobs WHERE {cond} FOR UPDATE", params).fetchone()
        if cur is None:
            return None
        if retryable and cur["attempts"] < cur["max_attempts"]:
            delay = backoff_base_s * (2 ** max(cur["attempts"] - 1, 0))
            conn.execute(
                "UPDATE jobs SET status = 'QUEUED', locked_until = NULL, last_error = %s, "
                "run_after = now() + make_interval(secs => %s), updated_at = now(), "
                "case_id = COALESCE(%s, case_id) WHERE tenant_id = %s AND job_id = %s",
                (error[:4000], delay, case_id, cur["tenant_id"], cur["job_id"]))
            return "QUEUED"
        _dead_letter(conn, cur, error=error, case_id=case_id)
        return "DEAD"


def _control_number(payload: dict) -> str | None:
    if not isinstance(payload, dict):
        return None
    env = payload.get("envelope")
    if isinstance(env, dict) and isinstance(env.get("acdv"), dict):
        return env["acdv"].get("control_number")
    return payload.get("control_number")


def _dead_letter(conn, job: dict, *, error: str, case_id: str | None = None) -> None:
    """Inside an open transaction: DEAD + escalate the case (fail safe) + audit event."""
    tenant_id = job["tenant_id"]
    case = repo.find_case_for_job(conn, tenant_id=tenant_id, case_id=case_id or job["case_id"],
                                  control_number=_control_number(job["payload"]))
    conn.execute("UPDATE jobs SET status = 'DEAD', locked_until = NULL, last_error = %s, updated_at = now(), "
                 "case_id = COALESCE(%s, case_id) WHERE tenant_id = %s AND job_id = %s",
                 (error[:4000], case["case_id"] if case else None, tenant_id, job["job_id"]))
    escalated = False
    if case is not None and state_machine.can_transition(case["state"], CaseState.ESCALATED):
        state_machine.transition(conn, tenant_id=tenant_id, case_id=case["case_id"], to=CaseState.ESCALATED,
                                 actor_type=ActorType.SYSTEM, actor_id=WORKER_ACTOR, reason="JOB_DEAD_LETTERED",
                                 detail={"job_id": job["job_id"], "error": error[:2000]})
        escalated = True
    append_event(conn, tenant_id=tenant_id, case_id=case["case_id"] if case else None,
                 event_type="JOB_DEAD_LETTERED", actor_type=ActorType.SYSTEM, actor_id=WORKER_ACTOR,
                 actor_role=None, payload={"job_id": job["job_id"], "kind": job["kind"],
                                           "attempts": job["attempts"], "error": error[:2000],
                                           "case_escalated": escalated,
                                           "control_number": _control_number(job["payload"])})


def reap_expired_leases(conn, *, tenant_ids: list[str] | None = None) -> dict:
    """Return expired RUNNING jobs to QUEUED, or dead-letter them when attempts are used up."""
    where, params = ["status = 'RUNNING'", "locked_until < now()"], []
    if tenant_ids is not None:
        where.append("tenant_id = ANY(%s)")
        params.append(list(tenant_ids))
    requeued = dead = 0
    with conn.transaction():
        rows = conn.execute(f"SELECT * FROM jobs WHERE {' AND '.join(where)} ORDER BY job_id "
                            "FOR UPDATE SKIP LOCKED", params).fetchall()
        for j in rows:
            if j["attempts"] >= j["max_attempts"]:
                _dead_letter(conn, j, error="lease expired; attempts exhausted")
                dead += 1
            else:
                conn.execute("UPDATE jobs SET status = 'QUEUED', locked_until = NULL, "
                             "last_error = 'lease expired', updated_at = now() WHERE tenant_id = %s AND job_id = %s",
                             (j["tenant_id"], j["job_id"]))
                requeued += 1
    return {"requeued": requeued, "dead": dead}


def counts(conn, *, tenant_ids: list[str] | None = None) -> dict[str, int]:
    where, params = "", []
    if tenant_ids is not None:
        where, params = "WHERE tenant_id = ANY(%s)", [list(tenant_ids)]
    with conn.transaction():
        rows = conn.execute(f"SELECT status, count(*) AS n FROM jobs {where} GROUP BY status", params).fetchall()
    return {r["status"]: r["n"] for r in rows}


def next_run_after_s(conn, *, kinds=("process_dispute",), tenant_ids: list[str] | None = None) -> float | None:
    """Seconds until the next QUEUED job becomes claimable (0 if one is ready), or None if none queued."""
    where, params = ["status = 'QUEUED'", "kind = ANY(%s)"], [list(kinds)]
    if tenant_ids is not None:
        where.append("tenant_id = ANY(%s)")
        params.append(list(tenant_ids))
    with conn.transaction():
        row = conn.execute(f"SELECT EXTRACT(EPOCH FROM min(run_after) - now()) AS s FROM jobs "
                           f"WHERE {' AND '.join(where)}", params).fetchone()
    return None if row["s"] is None else max(float(row["s"]), 0.0)
