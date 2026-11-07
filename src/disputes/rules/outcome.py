"""R-10 outcome rules, R-29 explainability. OWNER: rules agent.

Precedence: any escalation condition > MODIFY > VERIFY. All triggered reasons are recorded
as RuleFirings (rule ID + version + evidence IDs). The system never proposes DELETE.
INVARIANT (B1, ≥10,000 property tests): VERIFIED_AS_REPORTED ⇒ every month MATCH ∧ no
escalation ∧ every claim CONTRADICTED ∧ categories == {PAYMENT_HISTORY}.
"""
from __future__ import annotations

from disputes.domain import Claim, Classification, Decision, EscalationReason, Evidence, MonthComparison

RULES_VERSION = "1.0.0"


def decide(*, classification: Classification, comparisons: list[MonthComparison], evidence: list[Evidence],
           claims: list[Claim], upstream_escalations: tuple[EscalationReason, ...] = (),
           llm_note_flag: bool = False) -> Decision:
    """Inputs are everything known about the case so far; `upstream_escalations` carries
    reasons raised by intake / classification / claims / drafting (they force ESCALATED).
    - any NO_DATA -> EVIDENCE_MISSING
    - HARDSHIP/DEFERRAL/FORBEARANCE note overlapping a disputed month, or llm_note_flag -> EVIDENCE_CONFLICT
    - any claim SUPPORTED or NOT_ADDRESSABLE (when otherwise VERIFY) -> CLAIM_UNRESOLVED
    - any MISMATCH and no escalation -> MODIFY with a Correction per mismatched month
    - else VERIFIED_AS_REPORTED
    """
    raise NotImplementedError
