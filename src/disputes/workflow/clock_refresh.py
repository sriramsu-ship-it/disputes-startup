"""R-05 periodic clock refresh (STATUS known issue 2). OWNER: hardening (workflow).

Intake computes `cases.clock_state` once; this job re-evaluates it for every open case with the
intake clock function (`disputes.intake.clock.compute_clock`) so AT_RISK / BREACHED ordering in
the queue and the client portal's SLA tiles stay current.

- Writes only when something changes (clock state or internal target date), then updates the case
  and appends a CLOCK_STATE_CHANGED audit event (from/to, due date, internal target, evaluated_at,
  business days to target, holiday/time-zone table versions, rule id/version, config values used)
  in the same transaction. Unchanged cases produce no write: running it twice is a no-op.
- Safe with several workers: each case is re-read under `FOR UPDATE SKIP LOCKED` and compared
  inside that transaction, so two workers cannot both write the same change; a case locked by a
  reviewer is skipped and picked up on the next run. A session advisory lock lets only one worker
  run a pass at a time (others return at once).
- Does not bump `cases.version`: a clock flip must not invalidate a reviewer's open form (409).
- Newly BREACHED (PRD v1.3 §6.1 Q13): BREACHED is added to `escalation_reasons`, priority is raised
  to BREACHED_PRIORITY (sorts after ID fraud, before everything else), and a case not already
  ESCALATED is moved to ESCALATED through the state machine (actor SYSTEM, reason BREACHED). The
  reviewer's working decision (review artifacts) is kept; their next action on a stale form gets
  409. AT_RISK never changes state.
- Closed cases (SUBMITTED_STUB, OUT_OF_SCOPE) are not re-evaluated (Q13: the client owns
  OUT_OF_SCOPE cases).
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Callable

from disputes.audit.chain import append_event
from disputes.config import Config
from disputes.domain import ActorType, CaseState as S, ClockState, EscalationReason, to_jsonable
from disputes.workflow import state_machine

log = logging.getLogger(__name__)
ACTOR = "system:clock-refresh"
CLOSED_STATES = (S.SUBMITTED_STUB.value, S.OUT_OF_SCOPE.value)
_ADVISORY_KEY = 7_051_005   # arbitrary constant: "R-05"
BREACHED_PRIORITY = 50      # ID_FRAUD_SUSPECTED uses 100 (pipeline.FRAUD_PRIORITY)


def _default_compute():
    from disputes.intake.clock import compute_clock
    return compute_clock


def refresh_clocks(conn, *, cfg: Config, now: datetime | None = None, tenant_ids: list[str] | None = None,
                   compute: Callable | None = None, limit: int = 5000) -> dict:
    """One pass. Returns {checked, changed, newly_breached, skipped_locked, errors, ran}."""
    now = now or datetime.now(timezone.utc)
    compute = compute or _default_compute()
    stats = {"checked": 0, "changed": 0, "newly_breached": 0, "skipped_locked": 0, "errors": 0, "ran": False}
    if conn.info.transaction_status != 0:      # psycopg TransactionStatus.IDLE == 0
        conn.rollback()
    got = conn.execute("SELECT pg_try_advisory_lock(%s) AS ok", (_ADVISORY_KEY,)).fetchone()["ok"]
    conn.commit()
    if not got:
        return stats
    stats["ran"] = True
    try:
        where, params = ["NOT (state = ANY(%s))", "response_due_date IS NOT NULL"], [list(CLOSED_STATES)]
        if tenant_ids is not None:
            where.append("tenant_id = ANY(%s)")
            params.append(list(tenant_ids))
        with conn.transaction():
            ids = conn.execute(f"SELECT tenant_id, case_id FROM cases WHERE {' AND '.join(where)} "
                               "ORDER BY tenant_id, case_id LIMIT %s", [*params, limit]).fetchall()
        for ref in ids:
            try:
                _refresh_one(conn, ref["tenant_id"], ref["case_id"], cfg=cfg, now=now, compute=compute, stats=stats)
            except Exception as e:  # noqa: BLE001 - one bad case must not stop the pass (fail safe: logged)
                if conn.info.transaction_status != 0:
                    conn.rollback()
                stats["errors"] += 1
                log.error("clock refresh failed for %s: %s", ref["case_id"], type(e).__name__)
    finally:
        conn.execute("SELECT pg_advisory_unlock(%s)", (_ADVISORY_KEY,))
        conn.commit()
    return stats


def _refresh_one(conn, tenant_id: str, case_id: str, *, cfg: Config, now: datetime, compute, stats: dict) -> None:
    with conn.transaction():
        case = conn.execute(
            "SELECT case_id, tenant_id, state, clock_state, response_due_date, internal_target_date, "
            "escalation_reasons, priority FROM cases "
            "WHERE tenant_id = %s AND case_id = %s FOR UPDATE SKIP LOCKED", (tenant_id, case_id)).fetchone()
        if case is None:
            stats["skipped_locked"] += 1
            return
        if case["state"] in CLOSED_STATES or case["response_due_date"] is None:
            return
        stats["checked"] += 1
        info = compute(case["response_due_date"], now, cfg)
        new_state = ClockState(info.state).value
        if new_state == case["clock_state"] and info.internal_target == case["internal_target_date"]:
            return
        conn.execute("UPDATE cases SET clock_state = %s, internal_target_date = %s, updated_at = now() "
                     "WHERE tenant_id = %s AND case_id = %s",
                     (new_state, info.internal_target, tenant_id, case_id))
        newly_breached = new_state == ClockState.BREACHED.value and case["clock_state"] != ClockState.BREACHED.value
        append_event(conn, tenant_id=tenant_id, case_id=case_id, event_type="CLOCK_STATE_CHANGED",
                     actor_type=ActorType.SYSTEM, actor_id=ACTOR, actor_role=None,
                     payload=to_jsonable({
                         "rule_id": "R-05.CLOCK_REFRESH", "from": case["clock_state"], "to": new_state,
                         "case_state": case["state"], "due_date": info.due_date,
                         "internal_target_from": case["internal_target_date"],
                         "internal_target_to": info.internal_target, "evaluated_at": info.evaluated_at,
                         "business_days_to_target": info.business_days_to_target,
                         "table_versions": info.table_versions, "newly_breached": newly_breached,
                         "case_state_changed": newly_breached and case["state"] != S.ESCALATED.value
                         and state_machine.can_transition(case["state"], S.ESCALATED),
                         "config": {"internal_target_business_days_before_due":
                                    cfg.internal_target_business_days_before_due,
                                    "at_risk_business_days_before_target": cfg.at_risk_business_days_before_target}}))
        if newly_breached:
            _escalate_breached(conn, case)
        stats["changed"] += 1
        stats["newly_breached"] += int(newly_breached)


def _escalate_breached(conn, case: dict) -> None:
    """PRD v1.3 §6.1 Q13, inside the caller's transaction."""
    reasons = list(case["escalation_reasons"] or [])
    if EscalationReason.BREACHED.value not in reasons:
        reasons.append(EscalationReason.BREACHED.value)
    from disputes.db import repo
    repo.update_case_fields(conn, tenant_id=case["tenant_id"], case_id=case["case_id"], escalation_reasons=reasons,
                            priority=max(int(case["priority"] or 0), BREACHED_PRIORITY))
    if case["state"] != S.ESCALATED.value and state_machine.can_transition(case["state"], S.ESCALATED):
        state_machine.transition(conn, tenant_id=case["tenant_id"], case_id=case["case_id"], to=S.ESCALATED,
                                 actor_type=ActorType.SYSTEM, actor_id=ACTOR, reason="BREACHED",
                                 detail={"rule_id": "R-05.CLOCK_REFRESH", "prd": "v1.3 §6.1 Q13",
                                         "escalation_reasons": reasons})
