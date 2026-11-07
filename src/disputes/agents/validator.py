"""R-13 draft validator. OWNER: agents agent. Deterministic.

Stated limit: proves citations exist and quotes match; does not prove support.
"""
from __future__ import annotations

from disputes.domain import Draft, Evidence


def validate_draft(draft: Draft, evidence: list[Evidence], source_texts: dict[str, str]) -> list[str]:
    """Errors (empty = valid): LLM sentence without citation; unknown evidence ID; quote span not
    verbatim in its source (after normalisation); TEMPLATE sentence not matching its template;
    LLM sentence containing an outcome word (`outcome_words` table); > 150 words total."""
    raise NotImplementedError
