"""Shared builders for intake tests (synthetic data only)."""
from __future__ import annotations

import hashlib
from dataclasses import replace
from datetime import date, datetime, time
from zoneinfo import ZoneInfo

from disputes_core.contracts import Attachment, Dispute

NY = ZoneInfo("America/New_York")
LETTER = ("To whom it may concern at Example Fintech Lender (SYNTHETIC),\n"
          "My name is Test Person and I am writing about account ending 0000.\n"
          "My June 2026 payment was made on time.\nI have never been late on this account.\n"
          "Please investigate and correct my credit report.\nSincerely, Test Person (SYNTHETIC TEST PERSON)")


def make_attachment(text: str = LETTER, **kw) -> Attachment:
    base = dict(attachment_id="A1", file_name="consumer_letter.txt", media_type="text/plain", page_count=1,
                extracted_text=text, sha256=hashlib.sha256(text.encode()).hexdigest(), metadata={})
    base.update(kw)
    return Attachment(**base)


def make_dispute(**kw) -> Dispute:
    base = dict(tenant_id="t-test", channel="ACDV", source_schema_version="placeholder-acdv-0.1.0",
                raw_payload_sha256="0" * 64, synthetic=True, control_number="SYNCN-TEST-1", cra="SYNTH-CRA-1",
                date_received="2026-10-15", response_due_date="2026-11-12", account_number="SYNACCT0000000000",
                consumer_name="Test Person", dispute_codes=("PLH-PH-01",), disputed_months=("2026-06",),
                free_text="CONSUMER DISPUTES PAYMENT HISTORY JUN 2026", attachments=(make_attachment(),))
    base.update(kw)
    return Dispute(**base)


def eod(d: date | str, hour: int = 17) -> datetime:
    """End of business day (17:00) in the placeholder zone."""
    if isinstance(d, str):
        d = date.fromisoformat(d)
    return datetime.combine(d, time(hour), NY)


def dispute_from_envelope(envelope: dict, *, proposed_contract: bool):
    """Map a fixture envelope. With proposed_contract=True, apply the two acdv_to_dispute changes
    requested in docs/engineering/stage-notes/intake.md: (1) consumer_name None when first or last
    name is blank; (2) attachment render_hints copied into metadata["render_hints"]."""
    from disputes_core.contracts import acdv_to_dispute
    d = acdv_to_dispute(envelope)
    if not proposed_contract:
        return d
    a = envelope["acdv"]
    c = a.get("consumer") or {}
    first, last = (c.get("first_name") or "").strip(), (c.get("last_name") or "").strip()
    name = f"{first} {last}" if first and last else None
    hints = {x["attachment_id"]: x.get("render_hints") for x in a.get("attachments") or ()}
    atts = tuple(replace(t, metadata={**t.metadata, "render_hints": hints[t.attachment_id]})
                 if hints.get(t.attachment_id) is not None else t for t in d.attachments)
    return replace(d, consumer_name=name, attachments=atts)
