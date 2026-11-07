"""R-02 intake validation. OWNER: intake agent.

Pure function, no I/O.
"""
from __future__ import annotations

from disputes.contracts_bridge import Dispute
from disputes.domain import EscalationReason


def validate_dispute(dispute: Dispute) -> tuple[tuple[EscalationReason, ...], tuple[str, ...]]:
    """Return (escalations, error_messages).

    R-02: any required field (control number, CRA, date received, response due date, account
    number, consumer name, dispute code(s)) missing, empty, whitespace-only or unparseable
    (dates must be ISO 8601 YYYY-MM-DD) -> (INTAKE_INVALID,). R-05: missing due date ->
    INTAKE_INVALID. Free text and attachments may be empty. Never raises on bad input.
    """
    raise NotImplementedError
