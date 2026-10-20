"""Adapter contract tests (ADR-004, R-01 fixture shape)."""
import ast
import copy
import json
from pathlib import Path

import pytest

from disputes_core import contracts

SRC = Path(__file__).resolve().parents[1]
FIX = SRC / "data" / "fixtures" / "seed20261019_n200"
PINNED_ACDV_KEYS = {"synthetic", "fixture_schema_version", "control_number", "cra", "date_received",
                    "response_due_date", "account_number", "consumer", "dispute_codes", "disputed_months",
                    "free_text", "attachments"}
PINNED_ATTACHMENT_KEYS = {"synthetic", "attachment_id", "file_name", "media_type", "page_count", "metadata",
                          "render_hints", "extracted_text", "sha256"}


def test_fixture_shape_pinned(batch):
    for e in batch["acdvs"]:
        assert set(e["acdv"]) <= PINNED_ACDV_KEYS
        for a in e["acdv"]["attachments"]:
            assert set(a) == PINNED_ATTACHMENT_KEYS


def test_fixture_source_maps_all_committed_fixtures():
    ds = list(contracts.FixtureAcdvSource(FIX / "acdvs.jsonl").fetch())
    assert len(ds) == 200
    assert all(d.synthetic and d.channel == "ACDV" and d.tenant_id == "synthetic-tenant-0" for d in ds)


def test_mapping_fields(batch):
    e = next(x for x in batch["acdvs"] if x["acdv"].get("response_due_date") and x["acdv"]["attachments"])
    d = contracts.acdv_to_dispute(e)
    a = e["acdv"]
    assert d.control_number == a["control_number"] and d.response_due_date == a["response_due_date"]
    assert d.account_number == a["account_number"]
    assert d.consumer_name == f"{a['consumer']['first_name']} {a['consumer']['last_name']}"
    assert d.dispute_codes == tuple(a["dispute_codes"])
    assert d.attachments[0].sha256 == a["attachments"][0]["sha256"]
    assert len(d.raw_payload_sha256) == 64


def test_malformed_maps_without_crashing(batch):
    """Mapping must not throw on malformed fixtures; Stage 1 intake escalates them (R-02)."""
    mal = [x for x, l in zip(batch["acdvs"], batch["labels"]) if "malformed_input" in l["edge_tags"]]
    assert mal
    for e in mal:
        contracts.acdv_to_dispute(e)


def test_unknown_schema_version_rejected(batch):
    e = copy.deepcopy(batch["acdvs"][0])
    e["fixture_schema_version"] = "e-oscar-real-9.9"
    with pytest.raises(contracts.UnsupportedSchemaVersion):
        contracts.acdv_to_dispute(e)


def test_raw_hash_changes_with_payload(batch):
    e = copy.deepcopy(batch["acdvs"][0])
    h1 = contracts.acdv_to_dispute(e).raw_payload_sha256
    e["acdv"]["free_text"] += "x"
    assert contracts.acdv_to_dispute(e).raw_payload_sha256 != h1


def test_mock_sor_and_stub_sink():
    sor = contracts.MockSystemOfRecord(FIX / "sor_accounts.jsonl")
    d = next(contracts.FixtureAcdvSource(FIX / "acdvs.jsonl").fetch())
    assert sor.get_account(d.account_number)["account_number"] == d.account_number
    assert sor.get_account("SYNACCT0000000000") is None
    sink = contracts.StubResponseSink()
    h = sink.write_package({"synthetic": True, "outcome": "STUB"})
    assert len(h) == 64 and len(sink.packages) == 1


def test_core_does_not_import_oracle():
    """Circularity guard: production code must not reuse the label oracle."""
    for p in (SRC / "disputes_core").rglob("*.py"):
        tree = ast.parse(p.read_text())
        for node in ast.walk(tree):
            if isinstance(node, (ast.Import, ast.ImportFrom)):
                names = [a.name for a in node.names] + [getattr(node, "module", "") or ""]
                assert not any("synthgen" in n for n in names), p
