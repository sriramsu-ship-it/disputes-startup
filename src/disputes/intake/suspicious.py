"""R-14 deterministic suspicious-content detection. OWNER: intake agent.

Pattern list is a versioned reference table (`injection_patterns`, verified=false).
HIGH: role markers ("SYSTEM:", "assistant:"), override phrases ("ignore previous/all
instructions"), hidden text, zero-width characters. LOW: tool / JSON-call syntax, or an LLM
flag alone. Plain consumer requests ("delete this late payment") are NOT suspicious.
"""
from __future__ import annotations

from disputes.contracts_bridge import Dispute
from disputes.domain import AttachmentFinding, SuspicionResult


def detect(dispute: Dispute, findings: tuple[AttachmentFinding, ...], llm_flag: bool = False) -> SuspicionResult:
    """Scan letter bodies, ACDV free text, file names/metadata, plus hidden-text/zero-width findings."""
    raise NotImplementedError
