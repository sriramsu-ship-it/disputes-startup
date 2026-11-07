"""R-12 cited draft narrative (≤150 words). OWNER: agents agent.

Sentences: LLM sentences must cite ≥1 evidence ID; all other text comes from the versioned
template library (reference table `response_templates`). Outcome and corrected values are
TEMPLATE slots filled from the Decision, never written by the LLM.
"""
from __future__ import annotations

from disputes.domain import Claim, Decision, Draft, Evidence


def draft_narrative(decision: Decision, claims: list[Claim], evidence: list[Evidence], budget) -> Draft:
    """Draft, validate (validator.validate_draft), one retry, then Draft(valid=False) ->
    caller escalates DRAFT_INVALID."""
    raise NotImplementedError
