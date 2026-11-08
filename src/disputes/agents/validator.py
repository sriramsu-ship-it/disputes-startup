"""R-13 draft validator. OWNER: agents agent. Deterministic.

Stated limit: proves citations exist and quotes match; does not prove support.

Error strings start with a stable code so callers and tests can match on them:
  EMPTY_DRAFT, LLM_NO_CITATION, UNKNOWN_EVIDENCE_ID, QUOTE_SPAN_INVALID, QUOTE_NOT_VERBATIM,
  TEMPLATE_UNKNOWN, TEMPLATE_MISMATCH, OUTCOME_WORD, TOO_LONG.
"""
from __future__ import annotations

import re
from functools import lru_cache

from disputes import reference
from disputes.agents.text import find_span, normalise, words
from disputes.domain import Draft, Evidence, SentenceSource

MAX_WORDS = 150   # PRD R-12 default; Config.narrative_max_words overrides via max_words=
_SLOT = re.compile(r"\{([a-z_]+)\}")
_QUOTED = re.compile(r'"([^"]+)"')


@lru_cache(maxsize=None)
def templates() -> dict[str, str]:
    return {e["template_id"]: e["text"] for e in reference.load("response_templates")["entries"]}


@lru_cache(maxsize=None)
def template_regex(template_id: str) -> re.Pattern:
    text = templates()[template_id]
    parts, pos = [], 0
    for m in _SLOT.finditer(text):
        parts.append(re.escape(text[pos:m.start()]))
        parts.append(f"(?P<{m.group(1)}>.+?)")
        pos = m.end()
    parts.append(re.escape(text[pos:]))
    return re.compile("^" + "".join(parts) + "$", re.S)


@lru_cache(maxsize=None)
def _outcome_rx() -> re.Pattern:
    terms = [e["term"] for e in reference.load("outcome_words")["entries"]]
    alt = "|".join(re.escape(t).replace(r"\ ", r"\s+") for t in sorted(terms, key=len, reverse=True))
    return re.compile(r"(?<![A-Za-z])(" + alt + r")(?![A-Za-z])", re.I)


def outcome_terms_in(text: str) -> list[str]:
    return sorted({m.group(1).lower() for m in _outcome_rx().finditer(text or "")})


def validate_draft(draft: Draft, evidence: list[Evidence], source_texts: dict[str, str],
                   *, max_words: int = MAX_WORDS) -> list[str]:
    """Errors (empty = valid): LLM sentence without citation; unknown evidence ID; quote span not
    verbatim in its source (after normalisation); TEMPLATE sentence not matching its template;
    LLM sentence containing an outcome word (`outcome_words` table); > 150 words total.

    Outcome words inside a verified consumer quote are not counted (they are the consumer's own
    words, proven present in the source); everything else in an LLM sentence is checked."""
    errors: list[str] = []
    known = {e.evidence_id for e in evidence}
    if not draft.sentences:
        return ["EMPTY_DRAFT: no sentences"]
    total = 0
    for n, s in enumerate(draft.sentences, start=1):
        total += words(s.text)
        unknown = [i for i in s.evidence_ids if i not in known]
        if unknown:
            errors.append(f"UNKNOWN_EVIDENCE_ID: S{n} cites {', '.join(unknown)}")
        if s.source == SentenceSource.TEMPLATE:
            if s.template_id not in templates():
                errors.append(f"TEMPLATE_UNKNOWN: S{n} template_id {s.template_id!r}")
            elif not template_regex(s.template_id).match(s.text):
                errors.append(f"TEMPLATE_MISMATCH: S{n} does not match {s.template_id}")
            continue
        if s.source != SentenceSource.LLM:
            continue     # HUMAN text: reviewer-owned; only citations (above) and length are checked
        if not s.evidence_ids:
            errors.append(f"LLM_NO_CITATION: S{n} cites no evidence ID")
        span_texts = []
        for sid, a, b in s.quote_spans:
            src = source_texts.get(sid)
            if src is None or not (0 <= a < b <= len(src)):
                errors.append(f"QUOTE_SPAN_INVALID: S{n} span ({sid}, {a}, {b}) is not inside a known source")
                continue
            span_texts.append((sid, src[a:b]))
            if normalise(src[a:b]) not in normalise(s.text):
                errors.append(f"QUOTE_NOT_VERBATIM: S{n} does not contain the text of span ({sid}, {a}, {b})")
        residue = normalise(s.text)
        for q in _QUOTED.findall(residue):
            ok = any(normalise(q) == normalise(t) or find_span(q, source_texts[sid]) is not None
                     for sid, t in span_texts)
            if not ok:
                errors.append(f"QUOTE_NOT_VERBATIM: S{n} quote \"{q[:60]}\" not found in a cited source")
            else:
                residue = residue.replace(f'"{q}"', '""')
        bad = outcome_terms_in(residue)
        if bad:
            errors.append(f"OUTCOME_WORD: S{n} uses {', '.join(bad)}")
    if total > max_words:
        errors.append(f"TOO_LONG: {total} words > {max_words}")
    return errors
