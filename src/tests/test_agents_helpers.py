"""Shared helpers for the agents tests (no tests here).

`build_evidence` mirrors the evidence-ID scheme documented in disputes/rules/evidence.py so the
agents module can be tested before the rules agent's gather_evidence lands. It is a TEST
fixture builder, not product code. Content shapes are the agents module's assumptions; they are
listed in docs/engineering/stage-notes/agents.md for the integrator.
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

from disputes.contracts_bridge import Dispute, acdv_to_dispute
from disputes.domain import Evidence

FIXTURES = Path(__file__).resolve().parents[1] / "data" / "fixtures" / "seed20261019_n200"
NOW = datetime(2026, 11, 7, 12, 0, tzinfo=timezone.utc)


def _ev(eid, kind, content, source="mock_sor") -> Evidence:
    h = hashlib.sha256(json.dumps(content, sort_keys=True, default=str).encode()).hexdigest()
    return Evidence(evidence_id=eid, kind=kind, source=source, retrieved_at=NOW, sha256=h, content=content)


def _shift(month: str, k: int) -> str:
    y, m = int(month[:4]), int(month[5:7])
    t = y * 12 + (m - 1) + k
    return f"{t // 12:04d}-{t % 12 + 1:02d}"


def build_evidence(dispute: Dispute, account: dict | None, months) -> list[Evidence]:
    out: list[Evidence] = []
    if account:
        out.append(_ev("EV-ACCOUNT", "account", {k: account.get(k) for k in
                                                ("account_number", "product", "open_date", "scheduled_payment")}))
        window = {_shift(m, k) for m in months for k in range(-2, 3)}
        for c in account.get("cycles") or []:
            if c["cycle_month"] in window:
                out.append(_ev(f"EV-CYCLE-{c['cycle_month']}", "cycle", dict(c)))
        out.append(_ev("EV-PROFILE", "account", {"profile": {c["cycle_month"]: c["reported_rating"]
                                                            for c in account.get("cycles") or []}}))
        for i, n in enumerate(account.get("notes") or [], start=1):
            out.append(_ev(f"EV-NOTE-{i}", "note", dict(n)))
        for i, n in enumerate(account.get("free_text_notes") or [], start=1):
            out.append(_ev(f"EV-FTNOTE-{i}", "free_text_note", dict(n)))
    for a in dispute.attachments:
        out.append(_ev(f"EV-ATT-{a.attachment_id}", "attachment",
                       {"attachment_id": a.attachment_id, "file_name": a.file_name,
                        "extracted_text": a.extracted_text}, source="acdv"))
    out.append(_ev("EV-ACDV", "acdv", {"control_number": dispute.control_number,
                                       "dispute_codes": list(dispute.dispute_codes),
                                       "disputed_months": list(dispute.disputed_months),
                                       "free_text": dispute.free_text}, source="acdv"))
    return out


def load_fixture_cases(path: Path = FIXTURES):
    """[(dispute, account|None, label)] for the 200 committed fixtures (tests only read labels)."""
    accts = {}
    for line in (path / "sor_accounts.jsonl").read_text().splitlines():
        if line.strip():
            a = json.loads(line)
            accts[a["account_number"]] = a
    acdvs = [json.loads(l) for l in (path / "acdvs.jsonl").read_text().splitlines() if l.strip()]
    labels = [json.loads(l) for l in (path / "labels.jsonl").read_text().splitlines() if l.strip()]
    assert [a["case_id"] for a in acdvs] == [l["case_id"] for l in labels]
    out = []
    for env, lab in zip(acdvs, labels):
        d = acdv_to_dispute(env)
        out.append((d, accts.get(d.account_number), lab))
    return out


def batch_cases(batch):
    accts = {a["account_number"]: a for a in batch["accounts"]}
    out = []
    for env, lab in zip(batch["acdvs"], batch["labels"]):
        d = acdv_to_dispute(env)
        out.append((d, accts.get(d.account_number), lab))
    return out


class FakeClient:
    """Scripted LlmClient: `responses` is a list of dicts / exceptions / callables, consumed per
    attempt; `delay_s` sleeps before answering (for timeout tests)."""

    def __init__(self, responses, model_id="fake-model-1", delay_s=0.0):
        self.responses = list(responses)
        self.model_id = model_id
        self.delay_s = delay_s
        self.calls = []

    def complete_json(self, prompt_template_id, data, schema):
        import time
        from disputes.agents.llm import input_hashes, load_template
        from disputes.domain import LlmCallRecord
        self.calls.append((prompt_template_id, data))
        if self.delay_s:
            time.sleep(self.delay_s)
        r = self.responses.pop(0) if len(self.responses) > 1 else self.responses[0]
        if callable(r) and not isinstance(r, dict):
            r = r(prompt_template_id, data)
        if isinstance(r, BaseException):
            raise r
        return r, LlmCallRecord(model_id=self.model_id, prompt_template_id=prompt_template_id,
                                prompt_sha256=load_template(prompt_template_id)[2],
                                input_sha256s=input_hashes(data), output=r, error=None, latency_ms=0,
                                tokens_in=10, tokens_out=5, cost_usd=0.0, attempt=1)


def make_dispute(text="", free_text="CONSUMER DISPUTES PAYMENT HISTORY", codes=("PLH-PH-01",),
                 months=("2026-03",), extra_attachments=(), file_name="letter.txt", metadata=None):
    from disputes.contracts_bridge import Attachment
    atts = []
    if text is not None:
        atts.append(Attachment("A1", file_name, "text/plain", 1, text, "0" * 64, dict(metadata or {})))
    atts.extend(extra_attachments)
    return Dispute(tenant_id="synthetic-tenant-0", channel="ACDV", source_schema_version="placeholder-acdv-0.1.0",
                   raw_payload_sha256="0" * 64, synthetic=True, control_number="SYNCN-TEST", cra="SYNTH-CRA-1",
                   date_received="2026-10-01", response_due_date="2026-10-31", account_number="SYNACCT0000000001",
                   consumer_name="Test Person", dispute_codes=tuple(codes), disputed_months=tuple(months),
                   free_text=free_text, attachments=tuple(atts))


def cycle_ev(month, dpd, rating):
    return _ev(f"EV-CYCLE-{month}", "cycle", {"cycle_month": month, "dpd_at_cycle": dpd, "reported_rating": rating})


def note_ev(n, typ, start, end):
    return _ev(f"EV-NOTE-{n}", "note", {"note_id": f"N{n}", "type": typ, "start_date": start, "end_date": end})


def ftnote_ev(n, text):
    return _ev(f"EV-FTNOTE-{n}", "free_text_note", {"note_id": f"F{n}", "text": text})


def att_ev(aid, text, file_name="letter.txt"):
    return _ev(f"EV-ATT-{aid}", "attachment", {"attachment_id": aid, "file_name": file_name, "extracted_text": text},
               source="acdv")
