"""R-21: case reads by AUDITOR or ADMIN are audit events. OWNER: platform-core.

The web module calls `record_case_read` on every case view/export. Only AUDITOR and ADMIN
reads are recorded (R-21); other roles return None without writing.
"""
from __future__ import annotations

from disputes.audit.chain import append_event
from disputes.db import repo
from disputes.domain import ActorType, Role

AUDITED_READ_ROLES = frozenset({Role.AUDITOR, Role.ADMIN})


def record_case_read(conn, *, tenant_id: str, case_id: str, user_id: str, role, detail: dict | None = None):
    """Append a CASE_READ event (same transaction as the caller's, or its own). Raises
    repo.NotFound if the case is not in `tenant_id` (no events for other tenants' cases).
    Returns the inserted event row, or None when the role is not audited."""
    if Role(str(role)) not in AUDITED_READ_ROLES:
        return None
    with conn.transaction():
        repo.get_case(conn, tenant_id=tenant_id, case_id=case_id)
        return append_event(conn, tenant_id=tenant_id, case_id=case_id, event_type="CASE_READ",
                            actor_type=ActorType.HUMAN, actor_id=user_id, actor_role=str(Role(str(role))),
                            payload={"user_id": user_id, "role": str(Role(str(role))), "detail": detail or {}})
