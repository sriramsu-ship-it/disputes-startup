"""R-06 classification and R-07 routing. OWNER: agents agent."""
from __future__ import annotations

from disputes.contracts_bridge import Dispute
from disputes.domain import Classification


def classify(dispute: Dispute, budget) -> Classification:
    """Code mapping (dispute_code_map table) + fraud keyword list (fraud_keywords table) + LLM
    category set over free text and attachment text. CLASS_CONFLICT when the code mapping and LLM
    set disagree or the LLM says UNCERTAIN. Asymmetric fraud rule: any IDENTITY_FRAUD signal
    routes ESCALATE_FRAUD regardless. Confidence logged, never gates. LlmUnavailable propagates."""
    raise NotImplementedError


def route(categories: frozenset, fraud_signal: bool, conflict: bool):
    """R-07 precedence: fraud -> ESCALATE_FRAUD; conflict -> ESCALATE_CLASS_CONFLICT;
    >1 category -> ESCALATE_MULTI_ISSUE; exactly {PAYMENT_HISTORY} -> INVESTIGATE; else OUT_OF_SCOPE."""
    raise NotImplementedError
