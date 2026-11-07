"""R-02 intake validation. OWNER: intake agent.

Pure function, no I/O.
"""
from __future__ import annotations

import re
from datetime import date

from disputes.contracts_bridge import Dispute
from disputes.domain import EscalationReason

ISO_DATE = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}")   # used with fullmatch: no times, no offsets, no padding
REQUIRED_TEXT_FIELDS = ("control_number", "cra", "account_number", "consumer_name")
REQUIRED_DATE_FIELDS = ("date_received", "response_due_date")


def parse_iso_date(value) -> date | None:
    """Strict ISO 8601 calendar date `YYYY-MM-DD`; anything else (incl. surrounding spaces) -> None."""
    if not isinstance(value, str) or not ISO_DATE.fullmatch(value):
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        return None


def _blank(v) -> bool:
    return not isinstance(v, str) or not v.strip()


def validate_dispute(dispute: Dispute) -> tuple[tuple[EscalationReason, ...], tuple[str, ...]]:
    """Return (escalations, error_messages).

    R-02: any required field (control number, CRA, date received, response due date, account
    number, consumer name, dispute code(s)) missing, empty, whitespace-only or unparseable
    (dates must be ISO 8601 YYYY-MM-DD) -> (INTAKE_INVALID,). R-05: missing due date ->
    INTAKE_INVALID. Free text and attachments may be empty. Never raises on bad input.

    Error messages name the field and the problem only, never the value (R-27: no PII in
    messages that may reach operational logs).
    """
    errors: list[str] = []
    try:
        for f in REQUIRED_TEXT_FIELDS:
            v = getattr(dispute, f, None)
            if v is None:
                errors.append(f"{f}: missing")
            elif _blank(v):
                errors.append(f"{f}: empty or not text")
        for f in REQUIRED_DATE_FIELDS:
            v = getattr(dispute, f, None)
            if v is None:
                errors.append(f"{f}: missing")
            elif _blank(v):
                errors.append(f"{f}: empty")
            elif parse_iso_date(v) is None:
                errors.append(f"{f}: not an ISO 8601 date (YYYY-MM-DD)")
        codes = getattr(dispute, "dispute_codes", None)
        if not isinstance(codes, (tuple, list)) or not codes:
            errors.append("dispute_codes: missing or empty")
        elif any(_blank(c) for c in codes):
            errors.append("dispute_codes: contains an empty code")
    except Exception as exc:  # fail safe: a malformed object is invalid, never a crash
        errors.append(f"dispute: could not be validated ({type(exc).__name__})")
    if errors:
        return (EscalationReason.INTAKE_INVALID,), tuple(errors)
    return (), ()
