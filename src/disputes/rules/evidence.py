"""R-08 evidence retrieval from the SystemOfRecord. OWNER: rules agent.

Deterministic. Each item gets an evidence ID, source, retrieval timestamp and SHA-256 of
canonical content. Evidence IDs are stable and human-readable so citations are checkable:
  EV-ACCOUNT, EV-CYCLE-YYYY-MM, EV-PROFILE (reported payment profile), EV-NOTE-<n>,
  EV-FTNOTE-<n> (free-text notes), EV-ATT-<attachment_id>, EV-ACDV.

Conventions (rules module, v1):
- <n> in EV-NOTE-<n> / EV-FTNOTE-<n> is the 1-based position of the note in the SoR record's
  `notes` / `free_text_notes` list; the SoR's own `note_id` is kept in the content.
- The ledger (transactions) has no ID of its own in the scheme: each EV-CYCLE-<month> carries
  the cycle record plus `ledger_transactions`, the transactions posted in that calendar month.
- Window = union over disputed months of [month-2, month+2] (not the min..max span), limited to
  cycles that exist in the SoR. Malformed month strings are kept as disputed months (so the
  comparison produces NO_DATA -> EVIDENCE_MISSING) but do not widen the window.
- EV-ACCOUNT omits the consumer's SSN and DOB (minimisation, ADR-009); nothing in R-09/R-10
  or the drafts needs them.
"""
from __future__ import annotations

import re
from datetime import datetime

from disputes.audit.chain import canonical, sha256_hex
from disputes.contracts_bridge import Dispute
from disputes.domain import Evidence
from disputes_core.contracts import SystemOfRecord  # not re-exported by contracts_bridge yet (see notes)

MONTH_RE = re.compile(r"^(\d{4})-(0[1-9]|1[0-2])$")
WINDOW_MONTHS = 2
SOR_SOURCE = "mock_sor"
ACDV_SOURCE = "acdv"
_ACCOUNT_EXCLUDE = {"cycles", "notes", "free_text_notes", "transactions"}
_CONSUMER_EXCLUDE = {"ssn", "dob"}

__all__ = ["disputed_months", "gather_evidence", "window_months", "shift_month", "valid_month",
           "make_evidence", "SystemOfRecord"]


def valid_month(m) -> bool:
    return isinstance(m, str) and bool(MONTH_RE.match(m))


def shift_month(m: str, k: int) -> str:
    y, mo = int(m[:4]), int(m[5:7])
    idx = y * 12 + (mo - 1) + k
    return f"{idx // 12:04d}-{idx % 12 + 1:02d}"


def window_months(months: list[str], k: int = WINDOW_MONTHS) -> set[str]:
    out: set[str] = set()
    for m in months:
        if valid_month(m):
            out.update(shift_month(m, d) for d in range(-k, k + 1))
    return out


def disputed_months(dispute: Dispute, claim_months: set[str]) -> list[str]:
    """Months named in the ACDV ∪ months found in claims (R-11), sorted. Empty -> caller
    escalates MONTHS_UNDETERMINED. Blank/non-string entries are dropped; malformed but
    non-blank strings are kept (fail safe: they compare as NO_DATA)."""
    out = set()
    for m in tuple(dispute.disputed_months or ()) + tuple(claim_months or ()):
        if isinstance(m, str) and m.strip():
            out.add(m.strip())
    return sorted(out)


def make_evidence(evidence_id: str, kind: str, source: str, now: datetime, content: dict) -> Evidence:
    return Evidence(evidence_id=evidence_id, kind=kind, source=source, retrieved_at=now,
                    sha256=sha256_hex(canonical(content)), content=content)


def _acdv_content(d: Dispute) -> dict:
    return {
        "channel": d.channel, "source_schema_version": d.source_schema_version,
        "raw_payload_sha256": d.raw_payload_sha256, "synthetic": d.synthetic,
        "control_number": d.control_number, "cra": d.cra,
        "date_received": d.date_received, "response_due_date": d.response_due_date,
        "account_number": d.account_number, "consumer_name": d.consumer_name,
        "dispute_codes": list(d.dispute_codes), "disputed_months": list(d.disputed_months),
        "free_text": d.free_text,
        "attachment_ids": [a.attachment_id for a in d.attachments],
    }


def _account_content(acct: dict) -> dict:
    c = {k: v for k, v in acct.items() if k not in _ACCOUNT_EXCLUDE}
    if isinstance(c.get("consumer"), dict):
        c["consumer"] = {k: v for k, v in c["consumer"].items() if k not in _CONSUMER_EXCLUDE}
    return c


def gather_evidence(dispute: Dispute, sor: SystemOfRecord, months: list[str], now: datetime) -> list[Evidence]:
    """Account record, cycles for disputed months ±2 months, reported profile, structured notes,
    free-text notes, attachments and the ACDV itself. Missing account -> return what exists
    (the comparison will produce NO_DATA -> EVIDENCE_MISSING)."""
    ev: list[Evidence] = [make_evidence("EV-ACDV", "acdv", ACDV_SOURCE, now, _acdv_content(dispute))]
    for a in dispute.attachments:
        ev.append(make_evidence(f"EV-ATT-{a.attachment_id}", "attachment", ACDV_SOURCE, now, {
            "attachment_id": a.attachment_id, "file_name": a.file_name, "media_type": a.media_type,
            "page_count": a.page_count, "sha256": a.sha256, "extracted_text": a.extracted_text,
            "metadata": dict(a.metadata or {}),
        }))

    acct = sor.get_account(dispute.account_number) if dispute.account_number else None
    if not isinstance(acct, dict):
        return ev

    ev.append(make_evidence("EV-ACCOUNT", "account", SOR_SOURCE, now, _account_content(acct)))

    cycles = [c for c in acct.get("cycles") or () if isinstance(c, dict)]
    ev.append(make_evidence("EV-PROFILE", "profile", SOR_SOURCE, now, {
        "account_number": acct.get("account_number"),
        "profile": [{"cycle_month": c.get("cycle_month"), "reported_rating": c.get("reported_rating")}
                    for c in cycles],
    }))

    window = window_months(months)
    txns = [t for t in acct.get("transactions") or () if isinstance(t, dict)]
    by_month: dict[str, list[dict]] = {}
    for c in cycles:
        if c.get("cycle_month") in window:
            by_month.setdefault(c["cycle_month"], []).append(c)
    for m in sorted(by_month):
        rows = by_month[m]
        if len(rows) == 1:
            content = dict(rows[0])
        else:
            # Several SoR cycle rows for one month: never pick one silently. No DPD/rating at the
            # top level -> R-09 NO_DATA; R-10 also raises EVIDENCE_CONFLICT on `conflicting_rows`.
            content = {"cycle_month": m, "conflicting_rows": [dict(r) for r in rows]}
        content["ledger_transactions"] = [t for t in txns if str(t.get("posted_date", ""))[:7] == m]
        ev.append(make_evidence(f"EV-CYCLE-{m}", "cycle", SOR_SOURCE, now, content))

    for i, n in enumerate(acct.get("notes") or (), start=1):
        ev.append(make_evidence(f"EV-NOTE-{i}", "note", SOR_SOURCE, now, dict(n) if isinstance(n, dict) else {"raw": n}))
    for i, n in enumerate(acct.get("free_text_notes") or (), start=1):
        ev.append(make_evidence(f"EV-FTNOTE-{i}", "free_text_note", SOR_SOURCE, now,
                                dict(n) if isinstance(n, dict) else {"text": n}))
    return ev
