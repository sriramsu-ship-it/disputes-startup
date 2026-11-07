"""R-11 claim extraction, quote location, claim-to-evidence mapping. OWNER: agents agent."""
from __future__ import annotations

from disputes.contracts_bridge import Dispute
from disputes.domain import Claim, EscalationReason, Evidence


def locate_quote(quote: str, text: str) -> tuple[int, int] | None:
    """Exact match first, then whitespace- and quote-character-normalised match. Code, not LLM."""
    raise NotImplementedError


def extract_claims(dispute: Dispute, budget) -> tuple[list[Claim], tuple[EscalationReason, ...]]:
    """LLM returns claims with verbatim quotes; code locates spans. Unlocatable -> QUOTE_UNLOCATED."""
    raise NotImplementedError


def map_claims(claims: list[Claim], evidence: list[Evidence], budget) -> tuple[list[Claim], tuple[EscalationReason, ...]]:
    """LLM proposes finding + evidence IDs per claim; code checks: finding present, evidence IDs
    exist, CONTRADICTED/SUPPORTED cite ≥1 ID, NOT_ADDRESSABLE has reason. Else UNADDRESSED_CLAIM."""
    raise NotImplementedError
