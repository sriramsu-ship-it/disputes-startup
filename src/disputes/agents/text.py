"""Deterministic text helpers shared by the agents module (quote location, months, sentences).

Pure functions, no I/O. Used by code-side checks (R-11 quote location, R-13 validator) and by
the offline heuristic backend. Nothing here decides an outcome.
"""
from __future__ import annotations

import re

ZERO_WIDTH = "​‌‍⁠﻿"
# quote-character normalisation (R-11): curly/prime/guillemet variants -> ASCII
_QUOTE_MAP = {
    "‘": "'", "’": "'", "‚": "'", "‛": "'", "′": "'", "´": "'", "`": "'",
    "“": '"', "”": '"', "„": '"', "‟": '"', "″": '"', "«": '"', "»": '"',
    "–": "-", "—": "-", "−": "-", " ": " ",
}

MONTHS = {
    "january": 1, "jan": 1, "february": 2, "feb": 2, "march": 3, "mar": 3, "april": 4, "apr": 4,
    "may": 5, "june": 6, "jun": 6, "july": 7, "jul": 7, "august": 8, "aug": 8,
    "september": 9, "sept": 9, "sep": 9, "october": 10, "oct": 10, "november": 11, "nov": 11,
    "december": 12, "dec": 12,
}
MONTH_NAMES = ("January", "February", "March", "April", "May", "June", "July", "August",
               "September", "October", "November", "December")

_MONTH_WORD = re.compile(
    r"\b(" + "|".join(sorted(MONTHS, key=len, reverse=True)) + r")\.?,?\s+(?:of\s+)?((?:19|20)\d\d)\b",
    re.IGNORECASE)
_ISO_MONTH = re.compile(r"\b((?:19|20)\d\d)-(0[1-9]|1[0-2])\b(?!-\d)")
_ISO_DATE = re.compile(r"\b((?:19|20)\d\d)-(0[1-9]|1[0-2])-(0[1-9]|[12]\d|3[01])\b")
_SLASH_MONTH = re.compile(r"\b(0?[1-9]|1[0-2])/((?:19|20)\d\d)\b")
_MONTH_RE = re.compile(r"^\d{4}-(0[1-9]|1[0-2])$")


def is_month(s: str) -> bool:
    return isinstance(s, str) and bool(_MONTH_RE.match(s))


def month_label(m: str) -> str:
    """'2026-06' -> 'June 2026'."""
    y, mm = m.split("-")
    return f"{MONTH_NAMES[int(mm) - 1]} {y}"


def parse_months(text: str) -> list[str]:
    """Months a sentence refers to, as sorted unique 'YYYY-MM'.

    'June 2026', 'Jun. 2026', '2026-06', '06/2026'. A full ISO date (YYYY-MM-DD) counts only
    when the sentence names no month otherwise: in "told me on 2026-09-08 that the August 2026
    late payment ..." the disputed month is August, the date is when the call happened.
    """
    text = text or ""
    found = set()
    for m in _MONTH_WORD.finditer(text):
        found.add(f"{m.group(2)}-{MONTHS[m.group(1).lower()]:02d}")
    for m in _ISO_MONTH.finditer(text):
        found.add(f"{m.group(1)}-{m.group(2)}")
    for m in _SLASH_MONTH.finditer(text):
        found.add(f"{m.group(2)}-{int(m.group(1)):02d}")
    if not found:
        for m in _ISO_DATE.finditer(text):
            found.add(f"{m.group(1)}-{m.group(2)}")
    return sorted(found)


# ----------------------------------------------------------------------------- normalisation
def _norm_char(ch: str) -> str:
    return _QUOTE_MAP.get(ch, ch)


def normalise_with_map(text: str) -> tuple[str, list[int]]:
    """Normalised text plus, for each normalised char, its index in the original.

    Normalisation: drop zero-width chars, map quote/dash variants to ASCII, collapse any run of
    whitespace to one space, case preserved.
    """
    out: list[str] = []
    idx: list[int] = []
    prev_space = False
    for i, ch in enumerate(text):
        if ch in ZERO_WIDTH:
            continue
        ch = _norm_char(ch)
        if ch.isspace():
            if prev_space:
                continue
            out.append(" ")
            idx.append(i)
            prev_space = True
            continue
        prev_space = False
        out.append(ch)
        idx.append(i)
    return "".join(out), idx


def normalise(text: str) -> str:
    return normalise_with_map(text or "")[0].strip()


def find_span(quote: str, text: str) -> tuple[int, int] | None:
    """Exact match first, then whitespace/quote-character/zero-width normalised match.
    Returns (start, end) in the ORIGINAL text, or None."""
    if not quote or not text:
        return None
    q = quote.strip()
    if not q:
        return None
    i = text.find(q)
    if i >= 0:
        return (i, i + len(q))
    nt, idx = normalise_with_map(text)
    nq = normalise(q)
    if not nq:
        return None
    j = nt.find(nq)
    if j < 0:
        return None
    start = idx[j]
    end = idx[j + len(nq) - 1] + 1
    return (start, end)


# ----------------------------------------------------------------------------- sentences
_SENT_END = re.compile(r"(?<=[.!?])[\"')\]]*\s+(?=[\"'(\[]?[A-Z0-9{])")


def sentences(text: str) -> list[tuple[int, int, int]]:
    """Split into sentences: (start, end, line_no). Lines first, then sentence punctuation.
    Spans index the original text; surrounding whitespace is trimmed."""
    out = []
    pos = 0
    for line_no, line in enumerate((text or "").split("\n")):
        line_start = pos
        pos += len(line) + 1
        cut = 0
        bounds = [m.end() for m in _SENT_END.finditer(line)] + [len(line)]
        for b in bounds:
            seg = line[cut:b]
            lead = len(seg) - len(seg.lstrip())
            s, e = cut + lead, cut + len(seg.rstrip())
            if e > s:
                out.append((line_start + s, line_start + e, line_no))
            cut = b
    return out


def words(text: str) -> int:
    return len(re.findall(r"\S+", text or ""))
