"""Case state machine (PRD §6 'Case states'). The only way to change `cases.state`.

`transition` validates the move, applies role guards, updates the row and writes the
STATE_CHANGED audit event in the same transaction.
"""
from __future__ import annotations

import psycopg

from disputes.audit.chain import append_event
from disputes.db import repo
from disputes.domain import ActorType, CaseState as S, Role

ALLOWED: dict[S, frozenset[S]] = {
    S.RECEIVED: frozenset({S.CLASSIFIED, S.ESCALATED}),
    S.CLASSIFIED: frozenset({S.OUT_OF_SCOPE, S.INVESTIGATING, S.ESCALATED}),
    S.INVESTIGATING: frozenset({S.DRAFT_READY, S.ESCALATED}),
    S.DRAFT_READY: frozenset({S.IN_REVIEW, S.ESCALATED}),
    S.ESCALATED: frozenset({S.IN_REVIEW, S.OUT_OF_SCOPE}),
    S.OUT_OF_SCOPE: frozenset({S.ESCALATED}),
    S.IN_REVIEW: frozenset({S.APPROVED, S.AWAITING_SECOND_APPROVAL, S.ESCALATED, S.OUT_OF_SCOPE}),
    S.AWAITING_SECOND_APPROVAL: frozenset({S.APPROVED, S.IN_REVIEW, S.ESCALATED}),
    S.APPROVED: frozenset({S.SUBMITTED_STUB, S.ESCALATED}),
    S.SUBMITTED_STUB: frozenset({S.IN_REVIEW}),     # post-submission change -> new package version (R-20)
}

# Moves only a SUPERVISOR (or ADMIN) may make when the actor is human (PRD §6).
SUPERVISOR_ONLY: frozenset[tuple[S, S]] = frozenset({
    (S.ESCALATED, S.IN_REVIEW), (S.ESCALATED, S.OUT_OF_SCOPE),
    (S.AWAITING_SECOND_APPROVAL, S.APPROVED), (S.AWAITING_SECOND_APPROVAL, S.IN_REVIEW),
})
STAFF_ROLES = frozenset({Role.SPECIALIST, Role.SUPERVISOR, Role.ADMIN})


class IllegalTransition(ValueError):
    pass


class Forbidden(PermissionError):
    pass


def can_transition(frm: S | str, to: S | str) -> bool:
    return S(to) in ALLOWED.get(S(frm), frozenset())


def transition(conn: psycopg.Connection, *, tenant_id: str, case_id: str, to: S | str,
               actor_type: ActorType, actor_id: str, actor_role: Role | str | None = None,
               reason: str | None = None, detail: dict | None = None,
               expected_version: int | None = None) -> dict:
    """Move a case to `to`. Raises IllegalTransition / Forbidden. Returns the updated row."""
    to = S(to)
    with conn.transaction():
        case = repo.get_case(conn, tenant_id=tenant_id, case_id=case_id, for_update=True)
        frm = S(case["state"])
        if not can_transition(frm, to):
            raise IllegalTransition(f"{case_id}: {frm} -> {to} is not allowed")
        if actor_type == ActorType.HUMAN:
            role = Role(actor_role) if actor_role else None
            if role not in STAFF_ROLES:
                raise Forbidden(f"role {role} cannot change case state")
            if (frm, to) in SUPERVISOR_ONLY and role not in (Role.SUPERVISOR, Role.ADMIN):
                raise Forbidden(f"{frm} -> {to} needs SUPERVISOR")
        row = repo.set_state(conn, tenant_id=tenant_id, case_id=case_id, state=to.value,
                             expected_version=expected_version)
        append_event(conn, tenant_id=tenant_id, case_id=case_id, event_type="STATE_CHANGED",
                     actor_type=actor_type, actor_id=actor_id,
                     actor_role=str(actor_role) if actor_role else None,
                     payload={"from": frm.value, "to": to.value, "reason": reason, "detail": detail or {}})
        return row
