"""T2 red-team suite (Appendix B) and the committed v1 data sets. ALL DATA SYNTHETIC."""
from __future__ import annotations

import collections
import json
from pathlib import Path

from synthgen import cli, pii_guard
from synthgen.v1 import generator as g1, injections as inj, redteam

SRC = Path(__file__).resolve().parents[1]
V1_FIX = SRC / "data" / "fixtures" / "v1_seed20261107_n200"
T2_DIR = SRC / "data" / "redteam" / "t2_seed20261107"


def test_t2_meets_appendix_b_size_and_surfaces():
    data = redteam.generate_t2(20261107)
    per = collections.Counter(p["surface"] for p in data["pairs"])
    assert set(per) == set(inj.SURFACES)
    for s in ("injection_letter_body", "injection_hidden_text", "injection_acdv_free_text", "injection_file_metadata"):
        assert per[s] >= 20, per
    assert len(data["pairs"]) >= 100
    assert len({p["variant_id"] for p in data["pairs"]}) == len(data["pairs"])
    assert len(data["acdvs"]) == 2 * len(data["pairs"])
    # injections are tried on every kind of correct outcome, not only VERIFY
    assert {p["gold_outcome"] for p in data["pairs"]} >= {"VERIFIED_AS_REPORTED", "MODIFY", "ESCALATED", "OUT_OF_SCOPE"}
    assert any("ID_FRAUD_SUSPECTED" in p["gold_escalation_reasons"] for p in data["pairs"])


def test_t2_pairs_reference_cases_and_gold_matches():
    data = redteam.generate_t2(20261107)
    labels = {l["case_id"]: l for l in data["labels"]}
    for p in data["pairs"]:
        c, i = labels[p["clean_case_id"]], labels[p["injected_case_id"]]
        assert c["twin_group"] == i["twin_group"] == p["twin_group"]
        assert c["gold"] == i["gold"] and c["gold"]["outcome"] == p["gold_outcome"]
        assert i["injection"]["variant_id"] == p["variant_id"] and c["injection"] is None


def test_t2_control_numbers_unique_so_no_twin_is_a_duplicate():
    data = redteam.generate_t2(20261107)
    cns = [e["acdv"]["control_number"] for e in data["acdvs"]]
    assert len(cns) == len(set(cns))
    assert all(l["gold"]["outcome"] != "DUPLICATE_IGNORED" for l in data["labels"])


def test_committed_v1_fixture_matches_regeneration(tmp_path):
    m = cli.write_set_v1(tmp_path, 20261107, g1.generate(20261107, 200))
    stored = json.loads((V1_FIX / "manifest.json").read_text())
    assert stored["files_sha256"] == m["files_sha256"]
    assert stored["generator_version"] == "1.0.0"
    for f in ("acdvs.jsonl", "sor_accounts.jsonl", "labels.jsonl", "variant_report.json", "manifest.json"):
        assert (V1_FIX / f).read_bytes() == (tmp_path / f).read_bytes(), f


def test_committed_t2_matches_regeneration(tmp_path):
    m = cli.write_redteam(tmp_path, 20261107)
    stored = json.loads((T2_DIR / "manifest.json").read_text())
    assert stored["files_sha256"] == m["files_sha256"]


def test_committed_v1_files_have_no_real_looking_pii():
    for d in (V1_FIX, T2_DIR):
        for f in d.iterdir():
            assert pii_guard.find_real_looking_pii(f.read_text(encoding="utf-8")) == [], f


def test_committed_v1_fixtures_map_through_the_platform_contract():
    """Integration check: every committed v1 / T2 envelope maps to the canonical Dispute."""
    from disputes_core.contracts import FixtureAcdvSource, MockSystemOfRecord
    for d in (V1_FIX, T2_DIR):
        disputes = list(FixtureAcdvSource(d / "acdvs.jsonl").fetch())
        assert len(disputes) == sum(1 for _ in (d / "acdvs.jsonl").open())
        assert all(x.synthetic for x in disputes)
        sor = MockSystemOfRecord(d / "sor_accounts.jsonl")
        found = sum(1 for x in disputes if x.account_number and sor.get_account(x.account_number))
        assert found >= 0.95 * len(disputes)
