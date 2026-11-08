"""R-06 classification and R-07 routing. OWNER: agents agent."""
from __future__ import annotations

import re

from disputes import reference
from disputes.agents import schemas
from disputes.agents.text import normalise
from disputes.contracts_bridge import Dispute
from disputes.domain import Category, Classification, EscalationReason, Route

_CATS = {c.value for c in Category}


def code_categories(codes) -> tuple[frozenset[Category], tuple[str, ...]]:
    """Deterministic mapping via the `dispute_code_map` table. Returns (categories, unknown codes)."""
    table = {e["code"]: e["categories"] for e in reference.load("dispute_code_map")["entries"]}
    cats: set[Category] = set()
    unknown = []
    for c in codes or ():
        if c in table:
            cats |= {Category(x) for x in table[c]}
        else:
            unknown.append(c)
    return frozenset(cats), tuple(unknown)


def fraud_keyword_hits(texts) -> tuple[str, ...]:
    """Phrases from the `fraud_keywords` table found in any text (case-insensitive, normalised)."""
    phrases = [e["phrase"].lower() for e in reference.load("fraud_keywords")["entries"]]
    hay = " \n ".join(normalise(t).lower() for t in texts if t)
    hay = re.sub(r"\s+", " ", hay)
    return tuple(p for p in phrases if p in hay)


def classify_data(dispute: Dispute) -> dict:
    """What the classify prompt sees (all of it delimited untrusted data, R-14). The dispute codes
    are deliberately withheld so the LLM set is an independent check on the code mapping."""
    return {
        "bureau_free_text": dispute.free_text or "",
        "documents": [{"source_id": a.attachment_id, "file_name": a.file_name,
                       "metadata": dict(a.metadata or {}), "text": a.extracted_text or ""}
                      for a in dispute.attachments],
    }


def classify(dispute: Dispute, budget) -> Classification:
    """Code mapping (dispute_code_map table) + fraud keyword list (fraud_keywords table) + LLM
    category set over free text and attachment text. CLASS_CONFLICT when the code mapping and LLM
    set disagree or the LLM says UNCERTAIN. Asymmetric fraud rule: any IDENTITY_FRAUD signal
    routes ESCALATE_FRAUD regardless. Confidence logged, never gates. LlmUnavailable propagates.

    Final `categories` = code set ∪ LLM set (UNCERTAIN removed) ∪ {IDENTITY_FRAUD if any fraud
    signal}. Unknown dispute codes contribute nothing, so they show up as a disagreement.
    If the LLM reports suspicious content, budget.llm_flags records it (see CaseBudget)."""
    code_cats, _unknown = code_categories(dispute.dispute_codes)
    texts = [dispute.free_text or ""] + [a.extracted_text or "" for a in dispute.attachments]
    kw_hits = fraud_keyword_hits(texts)

    out = budget.call("classify", classify_data(dispute), schemas.CLASSIFY)
    llm_cats = frozenset(Category(c) for c in out["categories"] if c in _CATS)
    if not llm_cats:
        llm_cats = frozenset({Category.UNCERTAIN})
    if out.get("suspicious_content"):
        budget.flag_suspicious("classify", out.get("suspicious_reason", ""))
    conf = out.get("confidence")
    conf = float(conf) if isinstance(conf, (int, float)) else None   # logged only; never gates

    sources = []
    if Category.IDENTITY_FRAUD in code_cats:
        sources.append("code_table")
    if kw_hits:
        sources.append("keyword")
    if Category.IDENTITY_FRAUD in llm_cats:
        sources.append("llm")
    fraud = bool(sources)

    llm_definite = llm_cats - {Category.UNCERTAIN}
    conflict = Category.UNCERTAIN in llm_cats or code_cats != llm_definite
    categories = frozenset(code_cats | llm_definite | ({Category.IDENTITY_FRAUD} if fraud else set()))
    r = route(categories, fraud, conflict)
    esc = {
        Route.ESCALATE_FRAUD: (EscalationReason.ID_FRAUD_SUSPECTED,),
        Route.ESCALATE_CLASS_CONFLICT: (EscalationReason.CLASS_CONFLICT,),
        Route.ESCALATE_MULTI_ISSUE: (EscalationReason.MULTI_ISSUE,),
    }.get(r, ())
    return Classification(categories=categories, code_categories=code_cats, llm_categories=llm_cats,
                          fraud_signal_sources=tuple(sources), llm_confidence=conf, route=r,
                          escalations=esc)


def route(categories: frozenset, fraud_signal: bool, conflict: bool):
    """R-07 precedence: fraud -> ESCALATE_FRAUD; conflict -> ESCALATE_CLASS_CONFLICT;
    >1 category -> ESCALATE_MULTI_ISSUE; exactly {PAYMENT_HISTORY} -> INVESTIGATE; else OUT_OF_SCOPE."""
    cats = frozenset(Category(c) for c in categories) - {Category.UNCERTAIN}
    if fraud_signal or Category.IDENTITY_FRAUD in cats:
        return Route.ESCALATE_FRAUD
    if conflict:
        return Route.ESCALATE_CLASS_CONFLICT
    if len(cats) > 1:
        return Route.ESCALATE_MULTI_ISSUE
    if cats == {Category.PAYMENT_HISTORY}:
        return Route.INVESTIGATE
    return Route.OUT_OF_SCOPE
