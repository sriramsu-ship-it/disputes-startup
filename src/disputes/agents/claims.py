"""R-11 claim extraction, quote location, claim-to-evidence mapping. OWNER: agents agent."""
from __future__ import annotations

from dataclasses import replace

from disputes.agents import schemas
from disputes.agents.text import find_span, is_month, parse_months
from disputes.contracts_bridge import Dispute
from disputes.domain import Claim, ClaimFinding, EscalationReason, Evidence

FREE_TEXT = "FREE_TEXT"
_CLAIM_TYPES = {"DATE", "AMOUNT", "PAYMENT_EVENT", "ACCOUNT_STATUS", "AGREEMENT"}


def locate_quote(quote: str, text: str) -> tuple[int, int] | None:
    """Exact match first, then whitespace- and quote-character-normalised match. Code, not LLM.
    (Zero-width characters are also ignored in the normalised pass.)"""
    return find_span(quote, text)


def source_texts(dispute: Dispute) -> dict[str, str]:
    """source_id -> text for every claim source: each attachment, plus FREE_TEXT."""
    out = {a.attachment_id: a.extracted_text or "" for a in dispute.attachments}
    out[FREE_TEXT] = dispute.free_text or ""
    return out


def extract_data(dispute: Dispute) -> dict:
    docs = [{"source_id": a.attachment_id, "kind": "consumer_document", "file_name": a.file_name,
             "text": a.extracted_text} for a in dispute.attachments if (a.extracted_text or "").strip()]
    if (dispute.free_text or "").strip():
        docs.append({"source_id": FREE_TEXT, "kind": "bureau_free_text", "file_name": "",
                     "text": dispute.free_text})
    return {"documents": docs}


def extract_claims(dispute: Dispute, budget) -> tuple[list[Claim], tuple[EscalationReason, ...]]:
    """LLM returns claims with verbatim quotes; code locates spans. Unlocatable -> QUOTE_UNLOCATED.

    Months: the LLM's months (format-checked) ∪ months code parses from the located quote, so a
    month the model forgot still widens the evidence window (R-08). No documents -> no call."""
    data = extract_data(dispute)
    if not data["documents"]:
        return [], ()
    out = budget.call("extract_claims", data, schemas.EXTRACT_CLAIMS)
    if out.get("suspicious_content"):
        budget.flag_suspicious("extract_claims", out.get("suspicious_reason", ""))
    texts = source_texts(dispute)
    claims: list[Claim] = []
    unlocated = False
    for i, c in enumerate(out.get("claims") or [], start=1):
        sid = c.get("source_id") or ""
        quote = c.get("quote") or ""
        span = locate_quote(quote, texts[sid]) if sid in texts else None
        if span is None:
            unlocated = True
        months = {m for m in c.get("months") or [] if is_month(m)}
        if span is not None:
            months |= set(parse_months(texts[sid][span[0]:span[1]]))
        ctype = c.get("claim_type") if c.get("claim_type") in _CLAIM_TYPES else "PAYMENT_EVENT"
        claims.append(Claim(claim_id=f"CL-{i}", text=(c.get("text") or quote)[:500], quote=quote,
                            source_id=sid, span=span, claim_type=ctype, months=tuple(sorted(months))))
    return claims, ((EscalationReason.QUOTE_UNLOCATED,) if unlocated else ())


def _evidence_view(e: Evidence) -> dict:
    return {"evidence_id": e.evidence_id, "kind": e.kind, "source": e.source, "content": e.content}


def map_data(claims: list[Claim], evidence: list[Evidence]) -> dict:
    return {
        "claims": [{"claim_id": c.claim_id, "text": c.text, "quote": c.quote, "source_id": c.source_id,
                    "claim_type": c.claim_type, "months": list(c.months)} for c in claims],
        "evidence": [_evidence_view(e) for e in evidence],
    }


def check_mapping(m: dict | None, known_ids: set[str]) -> str | None:
    """None if the mapping is valid, else why not (R-11 code-side checks)."""
    if m is None:
        return "no mapping returned for this claim"
    f = m.get("finding")
    if f not in {x.value for x in ClaimFinding}:
        return "no finding"
    ids = list(m.get("evidence_ids") or [])
    bad = [i for i in ids if i not in known_ids]
    if bad:
        return f"unknown evidence ID(s): {', '.join(sorted(set(bad)))[:200]}"
    if f in ("SUPPORTED", "CONTRADICTED") and not ids:
        return f"{f} without an evidence ID"
    if f == "NOT_ADDRESSABLE" and not (m.get("reason") or "").strip():
        return "NOT_ADDRESSABLE without a reason"
    return None


def map_claims(claims: list[Claim], evidence: list[Evidence], budget) -> tuple[list[Claim], tuple[EscalationReason, ...]]:
    """LLM proposes finding + evidence IDs per claim; code checks: finding present, evidence IDs
    exist, CONTRADICTED/SUPPORTED cite ≥1 ID, NOT_ADDRESSABLE has reason. Else UNADDRESSED_CLAIM.

    An invalid mapping leaves the claim with finding=None and reason "MAPPING_INVALID: ..." so the
    reviewer must enter one (R-17). A free-text-note conflict reported by the model is exposed as
    budget.note_conflict for rules.decide(llm_note_flag=...). No claims -> no call."""
    if not claims:
        return [], ()
    out = budget.call("map_claims", map_data(claims, evidence), schemas.MAP_CLAIMS)
    if out.get("note_conflict"):
        budget.note_conflict = True
        budget.note_conflict_reason = (out.get("note_conflict_reason") or "")[:200]
    known = {e.evidence_id for e in evidence}
    by_id: dict[str, dict | None] = {}
    for m in out.get("mappings") or []:
        cid = m.get("claim_id")
        if cid in by_id:            # two different answers for one claim: treat as no valid answer
            if by_id[cid] != m:
                by_id[cid] = {"finding": None, "evidence_ids": [], "reason": "conflicting mappings"}
        else:
            by_id[cid] = m
    result = []
    unaddressed = False
    for c in claims:
        m = by_id.get(c.claim_id)
        problem = check_mapping(m, known)
        if problem:
            unaddressed = True
            result.append(replace(c, finding=None, evidence_ids=(), reason=f"MAPPING_INVALID: {problem}"))
        else:
            result.append(replace(c, finding=ClaimFinding(m["finding"]),
                                  evidence_ids=tuple(dict.fromkeys(m.get("evidence_ids") or [])),
                                  reason=(m.get("reason") or "")[:500]))
    return result, ((EscalationReason.UNADDRESSED_CLAIM,) if unaddressed else ())
