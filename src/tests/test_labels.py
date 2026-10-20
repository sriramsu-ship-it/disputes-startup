"""Label consistency: gold labels agree with the data they describe."""
from datetime import date

import pytest

from synthgen import bizdays, generator, oracle, tables


def _acct(batch):
    return {a["account_number"]: a for a in batch["accounts"]}


def test_claim_spans_locate_quotes_exactly(batch):
    for e, l in zip(batch["acdvs"], batch["labels"]):
        atts = {a["attachment_id"]: a["extracted_text"] for a in e["acdv"]["attachments"]}
        for c in l["claims"]:
            s, t = c["span"]
            assert atts[c["source"]][s:t] == c["quote"], l["case_id"]


def test_case_ids_unique(batch):
    ids = [e["case_id"] for e in batch["acdvs"]]
    assert len(ids) == len(set(ids))


def test_month_results_recomputed_from_sor(batch):
    accts = _acct(batch)
    for e, l in zip(batch["acdvs"], batch["labels"]):
        mr = l["gold"]["month_results"]
        if not mr:
            continue
        cycles = {c["cycle_month"]: c for c in accts[e["acdv"]["account_number"]]["cycles"]}
        for m, res in mr.items():
            if m not in cycles:
                assert res == "NO_DATA"
            else:
                exp = tables.rating_for_dpd(cycles[m]["dpd_at_cycle"])
                assert res == ("MATCH" if exp == cycles[m]["reported_rating"] else "MISMATCH")


def test_verify_invariant_on_gold(batch):
    """B1-style invariant on the GOLD labels: VERIFIED only if all months MATCH, no flags,
    every claim CONTRADICTED, category set == {PAYMENT_HISTORY}."""
    for l in batch["labels"]:
        g = l["gold"]
        if g["outcome"] == "VERIFIED_AS_REPORTED":
            assert l["categories"] == ["PAYMENT_HISTORY"]
            assert g["month_results"] and set(g["month_results"].values()) == {"MATCH"}
            assert g["escalation_reasons"] == []
            assert all(c["finding"] == "CONTRADICTED" for c in l["claims"])


def test_no_delete_ever(batch, trial):
    for l in batch["labels"] + trial["labels"]:
        assert "DELETE" not in l["gold"]["outcome"]


def test_modify_has_corrections_that_match_table(batch):
    accts = _acct(batch)
    for e, l in zip(batch["acdvs"], batch["labels"]):
        g = l["gold"]
        if g["outcome"] == "MODIFY":
            assert g["corrections"]
            cycles = {c["cycle_month"]: c for c in accts[e["acdv"]["account_number"]]["cycles"]}
            for c in g["corrections"]:
                assert c["corrected_rating"] == tables.rating_for_dpd(cycles[c["month"]]["dpd_at_cycle"])
                assert c["corrected_rating"] != c["reported_rating"]
        else:
            assert not g.get("corrections")


def test_escalated_has_reason_and_others_do_not(batch):
    for l in batch["labels"]:
        g = l["gold"]
        assert bool(g["escalation_reasons"]) == (g["outcome"] == "ESCALATED"), l["case_id"]


def test_scenario_intent_matches_gold(batch):
    for l in batch["labels"]:
        if l["scenario"] == "duplicate":
            assert l["gold"]["outcome"] == "DUPLICATE_IGNORED"
            continue
        exp = ("MODIFY", None) if "repeat" in l["edge_tags"] else generator.EXPECTED[l["scenario"]]
        generator.check_intent(l, exp)


def test_fraud_disguised_has_payment_history_code(batch):
    fr = [l for l in batch["labels"] if "identity_fraud_disguised" in l["adversarial_tags"]]
    assert fr
    for l in fr:
        assert l["dispute_code_categories"] == ["PAYMENT_HISTORY"]
        assert l["gold"]["escalation_reasons"][-1] == "ID_FRAUD_SUSPECTED"


def test_conflict_notes_overlap_and_near_miss_does_not(batch):
    accts = _acct(batch)
    for e, l in zip(batch["acdvs"], batch["labels"]):
        a = accts.get(e["acdv"].get("account_number"))
        if "conflicting_records" in l["edge_tags"]:
            assert any(oracle.note_overlaps(n, m) for n in a["notes"] for m in l["gold"]["disputed_months"])
        if "note_near_miss" in l["other_tags"]:
            assert not any(oracle.note_overlaps(n, m) for n in a["notes"] for m in l["gold"]["disputed_months"])


def test_repeat_links_prior_same_account_within_90_days(batch):
    by_cn = {e["acdv"]["control_number"]: e for e in batch["acdvs"] if "control_number" in e["acdv"]}
    reps = [(e, l) for e, l in zip(batch["acdvs"], batch["labels"]) if "repeat" in l["edge_tags"]]
    assert reps
    for e, l in reps:
        prior = by_cn[l["repeat_of"]]
        assert prior["acdv"]["account_number"] == e["acdv"]["account_number"]
        gap = (date.fromisoformat(e["acdv"]["date_received"]) - date.fromisoformat(prior["acdv"]["date_received"])).days
        assert 0 < gap <= 90


def test_duplicates_reuse_an_earlier_control_number(batch):
    seen = set()
    for e, l in zip(batch["acdvs"], batch["labels"]):
        cn = e["acdv"].get("control_number")
        if l["gold"]["outcome"] == "DUPLICATE_IGNORED":
            assert cn in seen
        if cn:
            seen.add(cn)


def test_injection_twins_differ_only_by_injection(batch):
    by_group = {}
    for e, l in zip(batch["acdvs"], batch["labels"]):
        if l["twin_group"]:
            by_group.setdefault(l["twin_group"], []).append((e, l))
    assert by_group
    for g, pair in by_group.items():
        assert len(pair) == 2, g
        (ce, cl), (ie, il) = sorted(pair, key=lambda p: bool(p[1]["adversarial_tags"]))
        assert not cl["adversarial_tags"] and il["adversarial_tags"]
        assert cl["gold"]["outcome"] == il["gold"]["outcome"]
        assert cl["gold"]["month_results"] == il["gold"]["month_results"]
        assert [c["quote"] for c in cl["claims"]] == [c["quote"] for c in il["claims"]]
        assert ce["acdv"]["control_number"] != ie["acdv"]["control_number"]
        assert ce["acdv"]["account_number"] != ie["acdv"]["account_number"]


def test_deadline_tags_match_clock(batch):
    for e, l in zip(batch["acdvs"], batch["labels"]):
        a = e["acdv"]
        if "malformed_input" in l["edge_tags"] or l["scenario"] == "duplicate":
            continue
        ingest = date.fromisoformat(e["fixture_meta"]["ingest_date"])
        due = date.fromisoformat(a["response_due_date"])
        state = bizdays.clock_state(ingest, due)
        if "deadline_breached" in l["edge_tags"]:
            assert state == "BREACHED" and "BREACHED" in l["gold"]["escalation_reasons"]
        elif "near_deadline" in l["edge_tags"]:
            assert state == "AT_RISK"
        elif "deadline_on_holiday" in l["edge_tags"]:
            assert not bizdays.is_business_day(due) and due.weekday() < 5
        else:
            assert state == "ON_TRACK"


def test_malformed_cases_fail_intake(batch):
    for e, l in zip(batch["acdvs"], batch["labels"]):
        if "malformed_input" in l["edge_tags"] and l["scenario"] != "duplicate":
            assert oracle.intake_problems(e["acdv"]) and l["gold"]["escalation_reasons"] == ["INTAKE_INVALID"]
        elif l["scenario"] != "duplicate":
            assert oracle.intake_problems(e["acdv"]) == []


def test_unreadable_docs_flagged(batch):
    for e, l in zip(batch["acdvs"], batch["labels"]):
        if "doc_unreadable" in l["edge_tags"]:
            assert any(oracle.attachment_unreadable(a) for a in e["acdv"]["attachments"])
        elif l["scenario"] != "duplicate":
            assert not any(oracle.attachment_unreadable(a) for a in e["acdv"]["attachments"])


def test_bizdays_basics():
    assert not bizdays.is_business_day(date(2026, 11, 26))  # Thanksgiving (placeholder table)
    assert not bizdays.is_business_day(date(2026, 7, 3))    # Sat Jul 4 observed Fri (6103(b))
    assert bizdays.add_business_days(date(2026, 11, 25), 1) == date(2026, 11, 27)
    assert bizdays.clock_state(date(2026, 12, 2), date(2026, 12, 1)) == "BREACHED"
