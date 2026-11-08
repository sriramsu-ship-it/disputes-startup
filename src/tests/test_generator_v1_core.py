"""Generator v1 (Stage 2, R-26 v1): determinism, schema, labels, strata, variety, PII, R-34, twins.

All data is SYNTHETIC. v0 behaviour is covered by the Stage 0 tests and must not change.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from datetime import date
from functools import lru_cache
from pathlib import Path

import jsonschema
import pytest
from hypothesis import given, settings, strategies as st

from synthgen import GENERATOR_VERSION, bizdays, cli, oracle, pii_guard, tables, vocab
from synthgen import isolation
from synthgen.v1 import generator as g1, injections as inj, phrasing as ph, redteam, report

SRC = Path(__file__).resolve().parents[1]
SCHEMAS = SRC / "synthgen" / "schemas"
SEED = 20261107


@lru_cache(maxsize=None)
def batch():
    return g1.generate(SEED, 1000)


@lru_cache(maxsize=None)
def t1_batch():
    return g1.generate(424242, 1100, g1.T1_MIX)


@lru_cache(maxsize=None)
def t2():
    return redteam.generate_t2(SEED)


def _bytes(data):
    return {k: "".join(json.dumps(r, sort_keys=True) + "\n" for r in data[k]) for k in ("acdvs", "accounts", "labels")}


def _validator(name):
    s = json.loads((SCHEMAS / f"{name}.schema.json").read_text())
    return jsonschema.Draft202012Validator(s)


def _sets():
    return {"batch": batch(), "t1": t1_batch(), "t2": t2()}


# ----------------------------------------------------------------- determinism / versioning
def test_v1_same_seed_identical():
    assert _bytes(g1.generate(7, 150)) == _bytes(g1.generate(7, 150))
    assert _bytes(redteam.generate_t2(3)) == _bytes(redteam.generate_t2(3))


def test_v1_different_seed_differs():
    assert _bytes(g1.generate(7, 150))["acdvs"] != _bytes(g1.generate(8, 150))["acdvs"]


@settings(max_examples=8, deadline=None)
@given(seed=st.integers(min_value=0, max_value=2**31 - 1))
def test_v1_determinism_property(seed):
    assert _bytes(g1.generate(seed, 100)) == _bytes(g1.generate(seed, 100))


def test_v1_cli_files_identical_across_runs_and_hash_seeds(tmp_path):
    hashes = []
    for i, hs in enumerate(["0", "12345"]):
        out = tmp_path / f"r{i}"
        env = {**os.environ, "PYTHONHASHSEED": hs}
        subprocess.run([sys.executable, "-m", "synthgen.cli", "generate", "--seed", "99", "--n", "120",
                        "--generator-version", "1.0.0", "--out", str(out)], cwd=SRC, env=env, check=True,
                       capture_output=True)
        hashes.append(json.loads((out / "manifest.json").read_text())["files_sha256"])
    assert hashes[0] == hashes[1]
    assert set(hashes[0]) == {"acdvs.jsonl", "sor_accounts.jsonl", "labels.jsonl", "variant_report.json"}


def test_cli_default_is_still_v0(tmp_path):
    cli.main(["generate", "--seed", "5", "--n", "100", "--out", str(tmp_path / "v0")])
    m = json.loads((tmp_path / "v0" / "manifest.json").read_text())
    assert m["generator_version"] == GENERATOR_VERSION == "0.1.0"
    assert not (tmp_path / "v0" / "variant_report.json").exists()


def test_v1_records_carry_version_and_supported_schema():
    for e in batch()["acdvs"]:
        assert e["generator_version"] == "1.0.0" and e["fixture_schema_version"] == "placeholder-acdv-0.1.0"
    assert all(l["generator_version"] == "1.0.0" for l in batch()["labels"])


# ----------------------------------------------------------------- schema / synthetic
@pytest.mark.parametrize("which", ["batch", "t1", "t2"])
def test_v1_schema_valid(which):
    data = _sets()[which]
    ve, va, vl = _validator("acdv_envelope"), _validator("sor_account"), _validator("label")
    assert [(e["case_id"], x.message) for e in data["acdvs"] for x in ve.iter_errors(e)] == []
    assert [x.message for a in data["accounts"] for x in va.iter_errors(a)] == []
    assert [(l["case_id"], x.message) for l in data["labels"] for x in vl.iter_errors(l)] == []


@pytest.mark.parametrize("which", ["batch", "t2"])
def test_v1_every_record_synthetic(which):
    data = _sets()[which]
    for e in data["acdvs"]:
        assert e["synthetic"] is True and e["acdv"]["synthetic"] is True and e["acdv"]["consumer"]["synthetic"] is True
        assert all(a["synthetic"] is True for a in e["acdv"]["attachments"])
    for a in data["accounts"]:
        assert a["synthetic"] is True
        assert all(x["synthetic"] is True for x in a["transactions"] + a["notes"] + a["free_text_notes"])
    assert all(l["synthetic"] is True for l in data["labels"])
    for k in ("pairs", "variants"):
        assert all(r["synthetic"] is True for r in data.get(k, []))


def test_v1_obviously_synthetic_markers():
    for e in batch()["acdvs"] + t2()["acdvs"]:
        a = e["acdv"]
        assert a["consumer"]["last_name"].strip() == "" or a["consumer"]["last_name"] in vocab.SURNAMES
        assert a["consumer"]["address"]["state"] == "ZZ" and a["cra"].startswith("SYNTH-CRA-")
        if a["attachments"] and a["attachments"][0]["attachment_id"] == "A1":
            assert "(SYNTHETIC TEST PERSON)" in a["attachments"][0]["extracted_text"]
    for acct in batch()["accounts"]:
        assert acct["furnisher"].endswith("(SYNTHETIC)") and acct["account_number"].startswith("SYNACCT")


# ----------------------------------------------------------------- PII guard
@pytest.mark.parametrize("which", ["batch", "t1", "t2"])
def test_v1_no_real_looking_pii(which):
    assert pii_guard.find_real_looking_pii(json.dumps(_sets()[which], ensure_ascii=False)) == []


def test_v1_pii_bait_present_and_fake():
    bait = [(e, l) for e, l in zip(batch()["acdvs"], batch()["labels"]) if "pii_bait" in l["adversarial_tags"]]
    assert bait
    for e, l in bait:
        kinds = {t.split(":")[1] for t in l["other_tags"] if t.startswith("pii_bait:")}
        assert len(kinds) >= 2


# ----------------------------------------------------------------- label consistency
@pytest.mark.parametrize("which", ["batch", "t1", "t2"])
def test_v1_claim_spans_locate_quotes_exactly(which):
    data = _sets()[which]
    n = 0
    for e, l in zip(data["acdvs"], data["labels"]):
        atts = {a["attachment_id"]: a["extracted_text"] for a in e["acdv"]["attachments"]}
        for c in l["claims"]:
            s, t = c["span"]
            assert atts[c["source"]][s:t] == c["quote"], l["case_id"]
            n += 1
    assert n > 0


def test_v1_claim_months_are_written_in_the_quote():
    """Typos never touch months: every labelled month appears in its quote in one of the formats."""
    for l in batch()["labels"] + t1_batch()["labels"]:
        for c in l["claims"]:
            for m in c["months"]:
                assert any(ph.month_text(m, s) in c["quote"] for s in ph.MONTH_STYLES), (l["case_id"], c["quote"])


def test_v1_claim_kinds_have_fixed_types():
    for l in batch()["labels"]:
        for c in l["claims"]:
            if c["claim_kind"] in ph.CLAIM_KINDS:
                assert c["claim_type"] == ph.CLAIM_KINDS[c["claim_kind"]][0]


def test_v1_month_results_and_invariants():
    data = batch()
    accts = {a["account_number"]: a for a in data["accounts"]}
    for e, l in zip(data["acdvs"], data["labels"]):
        gd = l["gold"]
        assert "DELETE" not in gd["outcome"]
        assert bool(gd["escalation_reasons"]) == (gd["outcome"] == "ESCALATED"), l["case_id"]
        if gd["month_results"]:
            cycles = {c["cycle_month"]: c for c in accts[e["acdv"]["account_number"]]["cycles"]}
            for m, res in gd["month_results"].items():
                if m not in cycles:
                    assert res == "NO_DATA"
                else:
                    exp = tables.rating_for_dpd(cycles[m]["dpd_at_cycle"])
                    assert res == ("MATCH" if exp == cycles[m]["reported_rating"] else "MISMATCH")
        if gd["outcome"] == "VERIFIED_AS_REPORTED":
            assert l["categories"] == ["PAYMENT_HISTORY"]
            assert set(gd["month_results"].values()) == {"MATCH"}
            assert all(c["finding"] == "CONTRADICTED" for c in l["claims"])
        if gd["outcome"] == "MODIFY":
            assert gd["corrections"]
        if l["scenario"] != "duplicate":
            exp = ("MODIFY", None) if "repeat" in l["edge_tags"] else g1.EXPECTED[l["scenario"]]
            g1.g0.check_intent(l, exp)


def test_v1_note_conflicts_structured_and_free_text():
    data = batch()
    accts = {a["account_number"]: a for a in data["accounts"]}
    seen_ft = seen_nm = 0
    for e, l in zip(data["acdvs"], data["labels"]):
        if l["scenario"] == "duplicate":
            continue
        a = accts.get(e["acdv"].get("account_number"))
        months = l["gold"]["disputed_months"]
        if "free_text_note_conflict" in l["other_tags"]:
            seen_ft += 1
            ids = {n["note_id"] for n in a["free_text_notes"]}
            assert l["note_conflicts"] and all(nc["note_id"] in ids for nc in l["note_conflicts"])
            assert any(oracle.note_overlaps(nc, m) for nc in l["note_conflicts"] for m in months)
            assert not any(n["type"] in oracle.CONFLICT_NOTE_TYPES and oracle.note_overlaps(n, m)
                           for n in a["notes"] for m in months)  # only the free-text note conflicts
            assert l["gold"]["escalation_reasons"] == ["EVIDENCE_CONFLICT"]
        if "free_text_note_near_miss" in l["other_tags"]:
            seen_nm += 1
            assert not l["note_conflicts"] and l["gold"]["outcome"] == "VERIFIED_AS_REPORTED"
        if "note_near_miss" in l["other_tags"]:
            assert not any(oracle.note_overlaps(n, m) for n in a["notes"] for m in months
                           if n["type"] in oracle.CONFLICT_NOTE_TYPES)
    assert seen_ft and seen_nm


def test_v1_background_notes_are_benign():
    bad = ("hardship", "deferral", "forbearance", "skip-payment", "do not report", "no late reporting")
    for a in batch()["accounts"]:
        for n in a["notes"]:
            if n["type"] not in oracle.CONFLICT_NOTE_TYPES:
                assert n["type"] in ("OTHER", "PRIOR_DISPUTE")
    labelled = {nc["note_id"] for l in batch()["labels"] for nc in l["note_conflicts"]}
    n_benign = 0
    for e, l in zip(batch()["acdvs"], batch()["labels"]):
        if l["scenario"] in ("duplicate", "ph_freetext_note_conflict", "ph_freetext_note_near_miss"):
            continue
        acct = next((a for a in batch()["accounts"] if a["account_number"] == e["acdv"].get("account_number")), None)
        for n in (acct or {}).get("free_text_notes", []):
            n_benign += 1
            assert not any(w in n["text"].lower() for w in bad), n["text"]
    assert n_benign > 100 and labelled


def test_v1_repeats_and_duplicates_linked():
    data = batch()
    by_cn = {e["acdv"]["control_number"]: e for e in data["acdvs"] if "control_number" in e["acdv"]}
    seen, reps = set(), 0
    for e, l in zip(data["acdvs"], data["labels"]):
        cn = e["acdv"].get("control_number")
        if l["gold"]["outcome"] == "DUPLICATE_IGNORED":
            assert cn in seen
        if "repeat" in l["edge_tags"]:
            reps += 1
            prior = by_cn[l["repeat_of"]]
            assert prior["acdv"]["account_number"] == e["acdv"]["account_number"]
            gap = (date.fromisoformat(e["acdv"]["date_received"]) - date.fromisoformat(prior["acdv"]["date_received"])).days
            assert 0 < gap <= 90
        if isinstance(cn, str) and cn.strip():
            seen.add(cn)
    assert reps


def test_v1_deadline_tags_match_clock():
    for e, l in zip(batch()["acdvs"], batch()["labels"]):
        if "malformed_input" in l["edge_tags"] or l["scenario"] == "duplicate":
            continue
        a = e["acdv"]
        state = bizdays.clock_state(date.fromisoformat(e["fixture_meta"]["ingest_date"]),
                                    date.fromisoformat(a["response_due_date"]))
        if "deadline_breached" in l["edge_tags"]:
            assert state == "BREACHED"
        elif "near_deadline" in l["edge_tags"]:
            assert state == "AT_RISK"


# ----------------------------------------------------------------- strata
@pytest.mark.parametrize("n", [100, 200, 1000])
def test_v1_shares_meet_r26(n):
    s = cli.summarise(g1.generate(11, n)["labels"])
    assert s["edge_case_share"] >= 0.15 and s["adversarial_share"] >= 0.10, s


@pytest.mark.parametrize("n", [200, 1000])
def test_v1_every_required_tag_present(n):
    s = cli.summarise(g1.generate(11, n)["labels"])
    assert g1.EDGE_TAGS <= set(s["edge_tags"]), g1.EDGE_TAGS - set(s["edge_tags"])
    assert g1.ADVERSARIAL_TAGS <= set(s["adversarial_tags"]), g1.ADVERSARIAL_TAGS - set(s["adversarial_tags"])


def test_v1_tags_from_closed_lists():
    for l in batch()["labels"]:
        assert set(l["edge_tags"]) <= g1.EDGE_TAGS and set(l["adversarial_tags"]) <= g1.ADVERSARIAL_TAGS


def test_v1_t1_mix_meets_appendix_b_strata():
    c = cli.t1_strata(t1_batch()["labels"])
    assert c["should_not_verify"] >= 600 and c["should_escalate"] >= 150, c
    assert c["identity_fraud_signal"] >= 150 and c["clean_should_verify"] >= 200, c


def test_v1_fraud_stratum_has_no_near_duplicates():
    """U34: a >=150-case fraud stratum without near-duplicates."""
    r = report.variant_report(t1_batch())["fraud"]
    assert r["cases"] >= 150
    assert r["distinct_combinations_used"] == r["cases"] == r["distinct_passage_skeletons"]
    assert r["max_shared_components_between_two_cases"] <= 1
    assert r["near_duplicate_pairs"] == 0, r
    assert r["indirect_phrasing_cases"] >= 30
    for l in t1_batch()["labels"]:
        if "identity_fraud_disguised" in l["adversarial_tags"]:
            assert l["dispute_code_categories"] == ["PAYMENT_HISTORY"]
            assert l["gold"]["escalation_reasons"][-1] == "ID_FRAUD_SUSPECTED"


# ----------------------------------------------------------------- variety minimums (U34)
def test_catalogs_have_at_least_20_variants_per_surface():
    cat = inj.catalog()
    assert set(cat) == set(inj.SURFACES)
    for s, vs in cat.items():
        assert len(vs) >= 20, s
        texts = [v["text"] for v in vs]
        assert len(set(texts)) == len(texts), s
        assert len({v["variant_id"] for v in vs}) == len(vs)


def test_catalog_expected_flags_follow_r14_classes():
    cat = inj.catalog()
    markers = ("system", "assistant", "ignore", "disregard", "forget", "developer", "ｓｙｓｔｅｍ")
    for v in cat["injection_tool_syntax"]:
        low = v["text"].lower()
        assert v["suspicious_expected"] == "LOW"
        assert not any(m in low for m in ("system", "assistant", "ignore", "disregard", "instruction"))
    for s in ("injection_letter_body", "injection_acdv_free_text", "injection_file_metadata"):
        for v in cat[s]:
            assert v["suspicious_expected"] == "HIGH"
            assert any(m in v["text"].lower().replace(" ", "").replace("-", "").replace(".", "")
                       or m in v["text"].lower() for m in markers), v
    assert all(v["suspicious_expected"] == "HIGH" for v in cat["injection_hidden_text"])


def test_claim_banks_and_letter_furniture_minimums():
    for kind, (_, tpls) in ph.CLAIM_KINDS.items():
        assert len(tpls) >= 10 and len(set(tpls)) == len(tpls), kind
    assert len(ph.GREETINGS) >= 12 and len(ph.CLOSINGS) >= 10 and len(ph.REQUESTS) >= 12
    assert len(ph.MONTH_STYLES) >= 6 and len(ph.DAY_STYLES) >= 6
    assert len(ph.FRAUD_DENIALS) * len(ph.FRAUD_EXPLANATIONS) * len(ph.FRAUD_ACTIONS) >= 5000


def test_variant_report_on_1000_case_set():
    r = report.variant_report(batch())
    for s, v in r["injection_surfaces"].items():
        assert v["catalog_variants"] >= 20 and v["distinct_variants_used"] >= min(20, v["cases"]), (s, v)
    for kind, v in r["claims_by_kind"].items():
        if v["claims"] >= 30:
            assert v["distinct_templates_used"] >= 0.8 * v["templates_available"], (kind, v)
    L = r["letters"]
    # free-text and metadata twins share their clean twin's letter text by design
    n_same = sum(1 for _, _, _, il in _twin_pairs(batch())
                 if il["injection"]["surface"] in ("injection_acdv_free_text", "injection_file_metadata"))
    assert L["distinct_letter_texts"] == L["letters"] - n_same
    assert L["distinct_greetings_used"] >= 12 and L["distinct_closings_used"] >= 10
    assert len(L["month_styles_used"]) >= 6 and len(L["day_styles_used"]) >= 5
    assert 0 < L["letters_with_typos"] < 0.6 * L["letters"]
    assert set(L["structures_used"]) >= {"standard", "single_paragraph", "long"}


# ----------------------------------------------------------------- injections and twins
def _twin_pairs(data):
    groups = {}
    for e, l, in zip(data["acdvs"], data["labels"]):
        if l["twin_group"]:
            groups.setdefault(l["twin_group"], []).append((e, l))
    out = []
    for g, pair in groups.items():
        assert len(pair) == 2, g
        (ce, cl), (ie, il) = sorted(pair, key=lambda p: p[1]["injection"] is not None)
        out.append((ce, cl, ie, il))
    return out


def _acct(data, no):
    return next(a for a in data["accounts"] if a["account_number"] == no)


@pytest.mark.parametrize("which", ["batch", "t2"])
def test_v1_twins_differ_only_by_the_injection(which):
    data = _sets()[which]
    pairs = _twin_pairs(data)
    assert pairs
    for ce, cl, ie, il in pairs:
        assert cl["injection"] is None and il["injection"] is not None
        assert not cl["adversarial_tags"] or cl["adversarial_tags"] == ["identity_fraud_disguised"]
        info = il["injection"]
        ca, ia = ce["acdv"], ie["acdv"]
        # identifiers differ (not a duplicate or repeat); everything else equal except the surface
        assert ca["control_number"] != ia["control_number"] and ca["account_number"] != ia["account_number"]
        skip = {"control_number", "account_number", "attachments", "free_text"}
        assert {k: v for k, v in ca.items() if k not in skip} == {k: v for k, v in ia.items() if k not in skip}
        ct, it = ca["attachments"][0]["extracted_text"], ia["attachments"][0]["extracted_text"]
        if info["surface"] in ("injection_letter_body", "injection_tool_syntax", "injection_hidden_text"):
            assert ct != it and g1.remove_spans(it, info["removal_spans"]) == ct
        else:
            assert ct == it
        if info["surface"] == "injection_acdv_free_text":
            assert ia["free_text"] == ca["free_text"] + info["free_text_suffix"]
        else:
            assert ia["free_text"] == ca["free_text"]
        if info["surface"] == "injection_file_metadata":
            assert (ia["attachments"][0]["file_name"], ia["attachments"][0]["metadata"]) != \
                   (ca["attachments"][0]["file_name"], ca["attachments"][0]["metadata"])
        else:
            assert ia["attachments"][0]["file_name"] == ca["attachments"][0]["file_name"]
            assert ia["attachments"][0]["metadata"] == ca["attachments"][0]["metadata"]
        assert ca["attachments"][1:] == ia["attachments"][1:]
        a1, a2 = _acct(data, ca["account_number"]), _acct(data, ia["account_number"])
        assert {k: v for k, v in a1.items() if k != "account_number"} == {k: v for k, v in a2.items() if k != "account_number"}
        assert [(c["quote"], c["finding"], c["months"]) for c in cl["claims"]] == \
               [(c["quote"], c["finding"], c["months"]) for c in il["claims"]]
        assert cl["gold"] == il["gold"] and cl["categories"] == il["categories"]
        assert cl["suspicious_expected"] == "NONE" and il["suspicious_expected"] in ("HIGH", "LOW")


@pytest.mark.parametrize("which", ["batch", "t2"])
def test_v1_injection_text_is_on_its_surface(which):
    data = _sets()[which]
    cat = {v["variant_id"]: v for vs in inj.catalog().values() for v in vs}
    for e, l in zip(data["acdvs"], data["labels"]):
        info = l.get("injection")
        if not info:
            if l["scenario"] != "duplicate":
                assert l["suspicious_expected"] == "NONE"
            continue
        v = cat[info["variant_id"]]
        a = e["acdv"]
        letter = a["attachments"][0]
        assert l["suspicious_expected"] == v["suspicious_expected"]
        if info["surface"] in ("injection_letter_body", "injection_tool_syntax"):
            assert v["text"] in letter["extracted_text"]
        elif info["surface"] == "injection_hidden_text":
            hs = letter["render_hints"]["hidden_spans"]
            assert len(hs) == 1 and hs[0]["style"] == v["style"]
            hidden = letter["extracted_text"][hs[0]["start"]:hs[0]["end"]]
            assert hidden.replace(inj.ZW, "").replace(inj.ZWJ, "") == v["text"]
            if v["style"] == "zero_width_interleaved":
                assert inj.ZW in hidden
        elif info["surface"] == "injection_acdv_free_text":
            assert a["free_text"].endswith(v["text"])
        else:
            assert letter["file_name"] == v["file_name"] and letter["metadata"] == v["metadata"]
        assert info["surface"] in l["adversarial_tags"]


def test_v1_negative_controls_not_suspicious():
    ctl = [l for l in batch()["labels"] if "imperative_negative_control" in l["other_tags"]]
    assert ctl and all(l["suspicious_expected"] == "NONE" for l in ctl)
    assert any("benign_lookalike_control" in l["other_tags"] for l in ctl)


# ----------------------------------------------------------------- R-34
def test_v1_eval_text_not_in_prompt_library():
    hs = set()
    for data in (batch(), t2()):
        hs |= isolation.eval_hashes(data["acdvs"], data["labels"])
    assert hs
    assert isolation.contaminated_files(SRC / "prompts", hs) == []
