"""R-08 evidence retrieval from the SystemOfRecord. OWNER: rules agent.

Deterministic. Each item gets an evidence ID, source, retrieval timestamp and SHA-256 of
canonical content. Evidence IDs are stable and human-readable so citations are checkable:
  EV-ACCOUNT, EV-CYCLE-YYYY-MM, EV-PROFILE (reported payment profile), EV-NOTE-<n>,
  EV-FTNOTE-<n> (free-text notes), EV-ATT-<attachment_id>, EV-ACDV.
"""
from __future__ import annotations

from datetime import datetime

from disputes.contracts_bridge import Dispute, SystemOfRecord
from disputes.domain import Evidence


def disputed_months(dispute: Dispute, claim_months: set[str]) -> list[str]:
    """Months named in the ACDV ∪ months found in claims (R-11), sorted. Empty -> caller
    escalates MONTHS_UNDETERMINED."""
    raise NotImplementedError


def gather_evidence(dispute: Dispute, sor: SystemOfRecord, months: list[str], now: datetime) -> list[Evidence]:
    """Account record, cycles for disputed months ±2 months, reported profile, structured notes,
    free-text notes, attachments and the ACDV itself. Missing account -> return what exists
    (the comparison will produce NO_DATA -> EVIDENCE_MISSING)."""
    raise NotImplementedError
