"""JSON schemas for each LLM step (ADR-005 §1). Output that does not validate is a failed call.

Kept to keywords that structured-output backends accept (type, enum, required, items,
additionalProperties:false). Formats the schema cannot express (YYYY-MM months, evidence-ID
existence, quote location) are checked by code after the call.
"""
from __future__ import annotations

_CATS = ["PAYMENT_HISTORY", "BALANCE", "ACCOUNT_STATUS", "IDENTITY_FRAUD", "OTHER", "UNCERTAIN"]
_CLAIM_TYPES = ["DATE", "AMOUNT", "PAYMENT_EVENT", "ACCOUNT_STATUS", "AGREEMENT"]
_FINDINGS = ["SUPPORTED", "CONTRADICTED", "NOT_ADDRESSABLE"]

_STR = {"type": "string"}
_STRS = {"type": "array", "items": {"type": "string"}}

CLASSIFY = {
    "type": "object",
    "additionalProperties": False,
    "required": ["categories", "confidence", "rationale", "suspicious_content", "suspicious_reason"],
    "properties": {
        "categories": {"type": "array", "items": {"type": "string", "enum": _CATS}},
        "confidence": {"type": "number"},
        "rationale": _STR,
        "suspicious_content": {"type": "boolean"},
        "suspicious_reason": _STR,
    },
}

EXTRACT_CLAIMS = {
    "type": "object",
    "additionalProperties": False,
    "required": ["claims", "suspicious_content", "suspicious_reason"],
    "properties": {
        "claims": {"type": "array", "items": {
            "type": "object",
            "additionalProperties": False,
            "required": ["text", "quote", "source_id", "claim_type", "months"],
            "properties": {
                "text": _STR, "quote": _STR, "source_id": _STR,
                "claim_type": {"type": "string", "enum": _CLAIM_TYPES},
                "months": _STRS,
            },
        }},
        "suspicious_content": {"type": "boolean"},
        "suspicious_reason": _STR,
    },
}

MAP_CLAIMS = {
    "type": "object",
    "additionalProperties": False,
    "required": ["mappings", "note_conflict", "note_conflict_reason"],
    "properties": {
        "mappings": {"type": "array", "items": {
            "type": "object",
            "additionalProperties": False,
            "required": ["claim_id", "finding", "evidence_ids", "reason"],
            "properties": {
                "claim_id": _STR,
                # null allowed on purpose: a missing finding is an UNADDRESSED_CLAIM (R-11), not a
                # transport failure, so it must reach the code-side check rather than be retried.
                "finding": {"type": ["string", "null"], "enum": _FINDINGS + [None]},
                "evidence_ids": _STRS,
                "reason": _STR,
            },
        }},
        "note_conflict": {"type": "boolean"},
        "note_conflict_reason": _STR,
    },
}

DRAFT = {
    "type": "object",
    "additionalProperties": False,
    "required": ["sentences"],
    "properties": {
        "sentences": {"type": "array", "items": {
            "type": "object",
            "additionalProperties": False,
            "required": ["text", "evidence_ids", "quotes"],
            "properties": {
                "text": _STR,
                "evidence_ids": _STRS,
                "quotes": {"type": "array", "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["source_id", "quote"],
                    "properties": {"source_id": _STR, "quote": _STR},
                }},
            },
        }},
    },
}

BY_TEMPLATE = {
    "classify": CLASSIFY,
    "extract_claims": EXTRACT_CLAIMS,
    "map_claims": MAP_CLAIMS,
    "draft": DRAFT,
}
