"""R-27 / ADR-009 PII hygiene for the web surfaces. OWNER: web agent.

- `mask_account` -> "••••1234" (last 4 only).
- `mask_text` masks SSN-shaped strings, synthetic account numbers (SYNACCT…) and long digit runs
  (8-19 digits) to their last 4, plus any names passed in.
- `PiiMaskingFilter` applies `mask_text` to every log record (message and args) so the
  operational log never carries those values. The audit store is NOT masked (ADR-009 §4).

Known limit: free-form personal names cannot be found by pattern; they are masked only when the
caller passes them (`names=`), or in log records that carry `pii_names` in `extra`.
"""
from __future__ import annotations

import logging
import re
from typing import Any, Iterable

_SSN = re.compile(r"(?<!\d)(\d{3})[- ]?(\d{2})[- ]?(\d{4})(?!\d)")
_ACCT = re.compile(r"\bSYNACCT[A-Z0-9]*?([A-Z0-9]{4})\b")
_DIGITS = re.compile(r"(?<![\d-])\d{4,15}(\d{4})(?![\d-])")
MASK = "••••"


def mask_account(acct: str | None) -> str:
    if not acct:
        return ""
    s = str(acct)
    return MASK + s[-4:] if len(s) > 4 else MASK + s


def mask_name(name: str | None) -> str:
    if not name:
        return ""
    parts = [p for p in str(name).split() if p]
    return " ".join(p[0] + "." for p in parts)


def mask_text(text: Any, names: Iterable[str] = ()) -> Any:
    if not isinstance(text, str):
        return text
    out = _SSN.sub(lambda m: "•••-••-" + m.group(3), text)
    out = _ACCT.sub(lambda m: MASK + m.group(1), out)
    out = _DIGITS.sub(lambda m: MASK + m.group(1), out)
    for n in sorted({n for n in names if n and len(n) >= 2}, key=len, reverse=True):
        out = re.sub(re.escape(n), mask_name(n), out, flags=re.IGNORECASE)
    return out


def mask_deep(obj: Any, names: Iterable[str] = ()) -> Any:
    """Recursively mask every string in a JSON-like structure (keys untouched)."""
    names = tuple(names)
    if isinstance(obj, str):
        return mask_text(obj, names)
    if isinstance(obj, dict):
        return {k: mask_deep(v, names) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [mask_deep(v, names) for v in obj]
    return obj


class PiiMaskingFilter(logging.Filter):
    """Attach to handlers (or loggers) that emit operational logs."""

    def filter(self, record: logging.LogRecord) -> bool:
        names = tuple(getattr(record, "pii_names", ()) or ())
        try:
            msg = record.getMessage()
        except Exception:  # noqa: BLE001 - never drop a log line because of formatting
            msg = str(record.msg)
        record.msg = mask_text(msg, names)
        record.args = ()
        return True


def install_log_masking(logger_names: Iterable[str] = ("", "disputes", "uvicorn", "uvicorn.access",
                                                       "uvicorn.error")) -> None:
    f = PiiMaskingFilter()
    for name in logger_names:
        lg = logging.getLogger(name)
        if not any(isinstance(x, PiiMaskingFilter) for x in lg.filters):
            lg.addFilter(f)
        for h in lg.handlers:
            if not any(isinstance(x, PiiMaskingFilter) for x in h.filters):
                h.addFilter(f)
