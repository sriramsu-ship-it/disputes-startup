"""R-12 cited draft narrative (≤150 words). OWNER: agents agent.

Sentences: LLM sentences must cite ≥1 evidence ID; all other text comes from the versioned
template library (reference table `response_templates`). Outcome and corrected values are
TEMPLATE slots filled from the Decision, never written by the LLM.
"""
from __future__ import annotations

from disputes import reference
from disputes.agents import schemas
from disputes.agents.claims import FREE_TEXT, locate_quote
from disputes.agents.text import month_label, words
from disputes.agents.validator import MAX_WORDS, templates, validate_draft
from disputes.domain import Claim, Decision, Draft, DraftSentence, Evidence, Outcome, SentenceSource


def _tpl(template_id: str, evidence_ids=(), **slots) -> DraftSentence:
    return DraftSentence(text=templates()[template_id].format(**slots), source=SentenceSource.TEMPLATE,
                         template_id=template_id, evidence_ids=tuple(evidence_ids))


def template_sentences(decision: Decision, known_ids: set[str]) -> tuple[list[DraftSentence], list[DraftSentence]]:
    """(before, after) the LLM sentences. Every slot value comes from the Decision."""
    fired = tuple(dict.fromkeys(i for f in decision.firings for i in f.evidence_ids if i in known_ids))
    before = [_tpl("TPL-INTRO")]
    after: list[DraftSentence] = []
    o = decision.outcome
    if o == Outcome.ESCALATED:
        reasons = ", ".join(r.value for r in decision.escalation_reasons) or "unspecified"
        after.append(_tpl("TPL-OUTCOME-ESCALATED", fired, reasons=reasons))
    else:
        after.append(_tpl(f"TPL-OUTCOME-{o.value}", fired))
    if o == Outcome.MODIFY:
        for c in decision.corrections:
            ids = tuple(i for i in (f"EV-CYCLE-{c.month}",) if i in known_ids)
            after.append(_tpl("TPL-CORRECTION", ids, month=month_label(c.month),
                              reported=c.reported or "none", corrected=c.corrected))
    after.append(_tpl("TPL-REVIEW"))
    return before, after


def default_source_texts(evidence: list[Evidence], claims: list[Claim] = ()) -> dict[str, str]:
    """Quote sources from the evidence: EV-ATT-<id> extracted text, and the ACDV free text."""
    out: dict[str, str] = {}
    for e in evidence:
        c = e.content or {}
        if e.evidence_id.startswith("EV-ATT-"):
            aid = c.get("attachment_id") or e.evidence_id.removeprefix("EV-ATT-")
            out[aid] = c.get("extracted_text") or c.get("text") or ""
        elif e.evidence_id == "EV-ACDV":
            ft = c.get("free_text")
            if ft is None and isinstance(c.get("acdv"), dict):
                ft = c["acdv"].get("free_text")
            if ft is not None:
                out[FREE_TEXT] = ft
    return out


def _evidence_brief(e: Evidence) -> dict:
    content = {k: v for k, v in (e.content or {}).items() if k not in ("extracted_text", "text", "transactions",
                                                                  "ledger_transactions", "cycles", "metadata")}
    return {"evidence_id": e.evidence_id, "kind": e.kind, "content": content}


def draft_data(claims: list[Claim], evidence: list[Evidence], word_limit: int, previous_errors=()) -> dict:
    cited = {i for c in claims for i in c.evidence_ids}
    keep = [e for e in evidence if e.evidence_id in cited or e.evidence_id.startswith("EV-ATT-")
            or e.evidence_id == "EV-ACDV"]
    return {
        "claims": [{"claim_id": c.claim_id, "quote": c.quote, "source_id": c.source_id,
                    "claim_type": c.claim_type, "months": list(c.months),
                    "finding": c.finding.value if c.finding else None,
                    "evidence_ids": list(c.evidence_ids), "reason": c.reason}
                   for c in claims if c.finding is not None],
        "evidence": [_evidence_brief(e) for e in keep],
        "word_limit": word_limit,
        "previous_errors": list(previous_errors),
    }


def _llm_sentences(out: dict, texts: dict[str, str]) -> list[DraftSentence]:
    res = []
    for s in out.get("sentences") or []:
        spans = []
        for q in s.get("quotes") or []:
            sid = q.get("source_id")
            span = locate_quote(q.get("quote") or "", texts[sid]) if sid in texts else None
            if span is not None:
                spans.append((sid, span[0], span[1]))
        res.append(DraftSentence(text=s.get("text") or "", source=SentenceSource.LLM, template_id=None,
                                 evidence_ids=tuple(dict.fromkeys(s.get("evidence_ids") or [])),
                                 quote_spans=tuple(spans)))
    return res


def draft_narrative(decision: Decision, claims: list[Claim], evidence: list[Evidence], budget,
                    *, source_texts: dict[str, str] | None = None, max_words: int | None = None) -> Draft:
    """Draft, validate (validator.validate_draft), one retry, then Draft(valid=False) ->
    caller escalates DRAFT_INVALID.

    `source_texts` (source_id -> text) should be passed by the pipeline (claims.source_texts(dispute));
    when omitted it is rebuilt from EV-ATT-* / EV-ACDV evidence. If the call cap leaves no room for
    the retry, the draft is returned invalid with a RETRY_SKIPPED note (never a silent pass).
    LlmUnavailable propagates (caller escalates LLM_UNAVAILABLE)."""
    limit = max_words or getattr(getattr(budget, "cfg", None), "narrative_max_words", None) or MAX_WORDS
    texts = source_texts if source_texts is not None else default_source_texts(evidence, claims)
    known = {e.evidence_id for e in evidence}
    before, after = template_sentences(decision, known)
    fixed_words = sum(words(s.text) for s in before + after)
    version = reference.load("response_templates")["table_version"]
    errors: list[str] = []
    attempt = 0
    while True:
        attempt += 1
        data = draft_data(claims, evidence, max(0, limit - fixed_words), errors)
        out = budget.call("draft", data, schemas.DRAFT)
        draft = Draft(sentences=tuple(before + _llm_sentences(out, texts) + after), attempts=attempt,
                      template_library_version=version)
        errors = validate_draft(draft, evidence, texts, max_words=limit)
        if not errors:
            return draft
        if attempt >= 2:
            return Draft(sentences=draft.sentences, validator_errors=tuple(errors), attempts=attempt,
                         valid=False, template_library_version=version)
        if not budget.can_call():
            return Draft(sentences=draft.sentences,
                         validator_errors=tuple(errors) + ("RETRY_SKIPPED: LLM call cap or time budget reached",),
                         attempts=attempt, valid=False, template_library_version=version)
