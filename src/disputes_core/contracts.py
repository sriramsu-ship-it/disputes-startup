"""ADR-004 integration boundary: canonical model and adapter protocols.

Stage 0 scope: shape only. `FixtureAcdvSource` reads synthetic fixture files and
maps the PLACEHOLDER ACDV fields to `Dispute`. It does NOT validate (R-02 is
Stage 1); a malformed fixture maps to a Dispute with None/raw values so intake can
escalate it later. Nothing here may import synthgen.oracle (test-enforced).
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterator, Protocol

SUPPORTED_FIXTURE_SCHEMA_VERSIONS = {"placeholder-acdv-0.1.0"}


class UnsupportedSchemaVersion(ValueError):
    pass


@dataclass(frozen=True)
class Attachment:
    attachment_id: str
    file_name: str
    media_type: str
    page_count: int
    extracted_text: str
    sha256: str
    metadata: dict = field(default_factory=dict)


@dataclass(frozen=True)
class Dispute:
    """Channel-agnostic canonical dispute (ACDV now; Reg V direct later)."""
    tenant_id: str
    channel: str                    # "ACDV" | "REG_V_DIRECT"
    source_schema_version: str
    raw_payload_sha256: str
    synthetic: bool
    control_number: str | None
    cra: str | None
    date_received: str | None       # raw string; parsed and validated in Stage 1 intake
    response_due_date: str | None
    account_number: str | None
    consumer_name: str | None
    dispute_codes: tuple[str, ...]
    disputed_months: tuple[str, ...]
    free_text: str | None
    attachments: tuple[Attachment, ...]


class AcdvSource(Protocol):
    def fetch(self) -> Iterator[Dispute]: ...


class SystemOfRecord(Protocol):
    def get_account(self, account_number: str) -> dict | None: ...


class ResponseSink(Protocol):
    def write_package(self, package: dict) -> str: ...


class LlmClient(Protocol):
    """Stage 2. Pinned model ID; no tools; structured output only (ADR-005/006)."""
    model_id: str
    def complete_json(self, prompt_template_id: str, data: dict, schema: dict) -> dict: ...


def canonical_json(obj) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def acdv_to_dispute(envelope: dict, tenant_id: str = "synthetic-tenant-0") -> Dispute:
    ver = envelope.get("fixture_schema_version")
    if ver not in SUPPORTED_FIXTURE_SCHEMA_VERSIONS:
        raise UnsupportedSchemaVersion(f"fixture_schema_version {ver!r} not supported")
    a = envelope["acdv"]
    c = a.get("consumer") or {}
    first, last = (c.get("first_name") or "").strip(), (c.get("last_name") or "").strip()
    name = f"{first} {last}".strip() or None
    return Dispute(
        tenant_id=tenant_id, channel="ACDV", source_schema_version=ver,
        raw_payload_sha256=hashlib.sha256(canonical_json(a).encode("utf-8")).hexdigest(),
        synthetic=bool(envelope.get("synthetic")) and bool(a.get("synthetic")),
        control_number=a.get("control_number"), cra=a.get("cra"),
        date_received=a.get("date_received"), response_due_date=a.get("response_due_date"),
        account_number=a.get("account_number"), consumer_name=name,
        dispute_codes=tuple(a.get("dispute_codes") or ()),
        disputed_months=tuple(a.get("disputed_months") or ()),
        free_text=a.get("free_text"),
        attachments=tuple(Attachment(x["attachment_id"], x["file_name"], x["media_type"], x["page_count"],
                                     x["extracted_text"], x["sha256"], dict(x.get("metadata") or {}))
                          for x in a.get("attachments") or ()),
    )


class FixtureAcdvSource:
    def __init__(self, path: Path):
        self.path = Path(path)

    def fetch(self) -> Iterator[Dispute]:
        with self.path.open(encoding="utf-8") as f:
            for line in f:
                if line.strip():
                    yield acdv_to_dispute(json.loads(line))


class MockSystemOfRecord:
    def __init__(self, path: Path):
        self._by_no = {}
        with Path(path).open(encoding="utf-8") as f:
            for line in f:
                if line.strip():
                    a = json.loads(line)
                    self._by_no[a["account_number"]] = a

    def get_account(self, account_number: str) -> dict | None:
        return self._by_no.get(account_number)


class StubResponseSink:
    """Records packages in memory. Nothing leaves the process."""
    def __init__(self):
        self.packages: list[dict] = []

    def write_package(self, package: dict) -> str:
        self.packages.append(package)
        return hashlib.sha256(canonical_json(package).encode("utf-8")).hexdigest()
