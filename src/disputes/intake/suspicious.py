"""R-14 deterministic suspicious-content detection. OWNER: intake agent.

Pattern list is a versioned reference table (`injection_patterns`, verified=false).
HIGH: role markers ("SYSTEM:", "assistant:"), override phrases ("ignore previous/all
instructions"), hidden text, zero-width characters. LOW: tool / JSON-call syntax, or an LLM
flag alone. Plain consumer requests ("delete this late payment") are NOT suspicious.

The flag is advisory: it is shown to the reviewer and (HIGH) triggers R-19 second approval.
It never changes the R-10 outcome. Detection only reads text; it never acts on it.
"""
from __future__ import annotations

import re
import unicodedata
from functools import lru_cache

from disputes import reference
from disputes.contracts_bridge import Dispute
from disputes.domain import AttachmentFinding, SuspicionLevel, SuspicionMatch, SuspicionResult
from disputes.intake.attachments import ZERO_WIDTH_CHARS, has_zero_width, hidden_spans, strip_zero_width

TABLE_ID = "injection_patterns"
EXCERPT_CHARS = 80
_RANK = {SuspicionLevel.NONE: 0, SuspicionLevel.LOW: 1, SuspicionLevel.HIGH: 2}


@lru_cache(maxsize=None)
def _compiled(version: str) -> tuple[tuple[str, SuspicionLevel, re.Pattern], ...]:
    t = reference.load(TABLE_ID)
    out = []
    for e in t["entries"]:
        if e.get("kind", "regex") != "regex":
            raise reference.TableError(f"{TABLE_ID}: unsupported pattern kind {e.get('kind')!r}")
        out.append((e["pattern_id"], SuspicionLevel(e["level"]),
                    re.compile(e["pattern"], re.IGNORECASE | re.MULTILINE)))
    return tuple(out)


def patterns() -> tuple[tuple[str, SuspicionLevel, re.Pattern], ...]:
    return _compiled(reference.load(TABLE_ID)["table_version"])


def patterns_version() -> str:
    return reference.load(TABLE_ID)["table_version"]


def normalise(text: str, *, file_name: bool = False) -> str:
    """NFKC (folds full-width / compatibility look-alikes), drop zero-width characters (they are
    flagged separately), and for file names turn '_', '-', '.' into spaces."""
    t = strip_zero_width(unicodedata.normalize("NFKC", text))
    if file_name:
        t = re.sub(r"[_\-.]+", " ", t)
    return t


def _excerpt(text: str, start: int, end: int) -> str:
    pad = max(0, (EXCERPT_CHARS - (end - start)) // 2)
    s = text[max(0, start - pad):min(len(text), end + pad)]
    s = " ".join(s.split())
    return s[:EXCERPT_CHARS]


def scan_text(text, surface: str, *, file_name: bool = False) -> list[SuspicionMatch]:
    """Pattern matches in one piece of untrusted text (one match per pattern per text)."""
    if not isinstance(text, str) or not text:
        return []
    out = []
    norm = normalise(text, file_name=file_name)
    for pid, level, rx in patterns():
        m = rx.search(norm)
        if m:
            out.append(SuspicionMatch(surface=surface, pattern_id=pid, level=level,
                                      excerpt=_excerpt(norm, m.start(), m.end())))
    if has_zero_width(text):
        i = next(i for i, c in enumerate(text) if c in ZERO_WIDTH_CHARS)
        out.append(SuspicionMatch(surface=surface, pattern_id="ZERO_WIDTH_CHARS", level=SuspicionLevel.HIGH,
                                  excerpt=_excerpt(strip_zero_width(text), max(0, i - 10), i + 10)))
    return out


def _metadata_strings(md) -> list[str]:
    out: list[str] = []

    def walk(o):
        if isinstance(o, str):
            out.append(o)
        elif isinstance(o, dict):
            for k, v in o.items():
                if k == "render_hints":      # rendering hints are our own extraction output, not consumer text
                    continue
                walk(v)
        elif isinstance(o, (list, tuple)):
            for v in o:
                walk(v)
    walk(md)
    return out


def detect(dispute: Dispute, findings: tuple[AttachmentFinding, ...], llm_flag: bool = False) -> SuspicionResult:
    """Scan letter bodies, ACDV free text, file names/metadata, plus hidden-text/zero-width findings."""
    matches: list[SuspicionMatch] = []
    matches += scan_text(getattr(dispute, "free_text", None), "free_text")
    by_id = {f.attachment_id: f for f in findings or ()}
    for att in getattr(dispute, "attachments", None) or ():
        matches += scan_text(getattr(att, "extracted_text", None), "letter_body")
        matches += scan_text(getattr(att, "file_name", None), "file_metadata", file_name=True)
        for s in _metadata_strings(getattr(att, "metadata", None)):
            matches += scan_text(s, "file_metadata")
        f = by_id.get(str(getattr(att, "attachment_id", "")))
        if f is not None and f.hidden_text:
            text = att.extracted_text if isinstance(att.extracted_text, str) else ""
            spans = hidden_spans(att)
            ex = " ".join(strip_zero_width(text[spans[0][0]:spans[0][1]]).split())[:EXCERPT_CHARS] if spans else ""
            matches.append(SuspicionMatch(surface="hidden_text", pattern_id="INVISIBLE_TEXT",
                                          level=SuspicionLevel.HIGH, excerpt=ex or f"attachment {f.attachment_id}"))
    # Zero-width characters reported by R-03 findings but not seen above (e.g. findings from a
    # richer extractor): still HIGH.
    if any(f.zero_width for f in findings or ()) and not any(m.pattern_id == "ZERO_WIDTH_CHARS" for m in matches):
        ids = ",".join(f.attachment_id for f in findings if f.zero_width)
        matches.append(SuspicionMatch(surface="hidden_text", pattern_id="ZERO_WIDTH_CHARS",
                                      level=SuspicionLevel.HIGH, excerpt=f"attachment {ids}"))
    if llm_flag:
        matches.append(SuspicionMatch(surface="llm_flag", pattern_id="LLM_FLAG", level=SuspicionLevel.LOW,
                                      excerpt="model flagged possible instructions in the data"))
    level = max((m.level for m in matches), key=_RANK.__getitem__, default=SuspicionLevel.NONE)
    return SuspicionResult(level=level, matches=tuple(matches), patterns_version=patterns_version())
