"""Unit and PRD §6 acceptance tests for the rules module (R-08, R-09, R-10, R-29, R-35)."""
from __future__ import annotations

import json
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path

import pytest

from disputes.audit.chain import canonical, sha256_hex
from disputes.config import Config
from disputes.contracts_bridge import Attachment, Dispute, FixtureAcdvSource, MockSystemOfRecord
from disputes.domain import (Category, Claim, ClaimFinding, Classification, EscalationReason as ER,
                             MonthResult, Outcome, Route)
from disputes.rules import gate
from disputes.rules.compare import compare_months, expected_rating
from disputes.rules.evidence import disputed_months, gather_evidence, shift_month, window_months
from disputes.rules.outcome import RULES_VERSION, decide, note_overlaps

NOW = datetime(2026, 10, 9, 12, tzinfo=timezone.utc)
FIX = Path(__file__).resolve().parents[1] / "data" / "fixtures" / "seed20261019_n200"
PH = Classification(frozenset({Category.PAYMENT_HISTORY}), frozenset({Category.PAYMENT_HISTORY}),
                    frozenset({Category.PAYMENT_HISTORY}), (), None, Route.INVESTIGATE)


# ------------------------------------------------------------------ helpers
class FakeSor:
    def __init__(self, accts):
        self.accts = {a["account_number"]: a for a in accts}

    def get_account(self, n):
        return self.accts.get(n)


def cyc(m, dpd, rating):
    return {"cycle_month": m, "cycle_date": f"{m}-25", "dpd_at_cycle": dpd, "reported_rating": rating, "balance": 100}


def account(cycles, notes=(), ft=(), txns=()):
    return {"account_number": "SYNACCT1", "consumer": {"first_name": "A", "last_name": "B", "ssn": "992-00-0001",
                                                        "dob": "1990-01-01"},
            "cycles": list(cycles), "notes": list(notes), "free_text_notes": list(ft), "transactions": list(txns),
            "synthetic": True}


def dispute(months=("2026-03",), attachments=()):
    return Dispute("t", "ACDV", "placeholder-acdv-0.1.0", "h", True, "CN1", "CRA1", "2026-10-01", "2026-10-30",
                   "SYNACCT1", "A B", ("PLH-01",), tuple(months), "free", tuple(attachments))


def claim(cid="C1", finding=ClaimFinding.CONTRADICTED, ids=("EV-CYCLE-2026-03",), months=("2026-03",)):
    return Claim(cid, "t", "q", "A1", (0, 1), "PAYMENT_EVENT", tuple(months), finding, tuple(ids))


def run(acct, months=("2026-03",), claims=None, cls=PH, upstream=(), llm_flag=False):
    d = dispute(months)
    claims = [claim()] if claims is None else claims
    ms = disputed_months(d, {m for c in claims for m in c.months})
    ev = gather_evidence(d, FakeSor([acct] if acct else []), ms, NOW)
    comps = compare_months(ms, ev)
    return decide(classification=cls, comparisons=comps, evidence=ev, claims=claims,
                  upstream_escalations=tuple(upstream), llm_note_flag=llm_flag), comps, ev


def firing_for(dec, result):
    return [f for f in dec.firings if f.result == result]


# ------------------------------------------------------------------ R-35 gate
def test_gate_synthetic_passes_and_returns_versions():
    v = gate.check_tables(Config())
    assert {"payment_rating_map", "dispute_code_map", "holiday_calendar", "time_zone"} <= set(v)
    assert all(set(x) == {"version", "verified"} for x in v.values())


def test_gate_live_refuses_unverified():
    with pytest.raises(gate.UnverifiedTables, match="payment_rating_map"):
        gate.check_tables(Config(mode="live"))


def test_gate_live_passes_when_all_verified():
    t = {"a": {"table_id": "a", "table_version": "1.0.0", "verified": True, "source": "CRRG 2026", "entries": []}}
    assert gate.check_tables(Config(mode="live"), t) == {"a": {"version": "1.0.0", "verified": True}}


@pytest.mark.parametrize("bad", [{"verified": "false"}, {"verified": None}, {"source": ""}, {"source": None},
                                 {"table_id": "other"}])
def test_gate_rejects_malformed_tables(bad):
    t = {"a": {"table_id": "a", "table_version": "1", "verified": True, "source": "s", "entries": [], **bad}}
    with pytest.raises(gate.MalformedTable):
        gate.check_tables(Config(), t)


def test_gate_rejects_unknown_mode():
    with pytest.raises(ValueError):
        gate.check_tables(Config(mode="Live "))


# ------------------------------------------------------------------ R-08
def test_disputed_months_union_sorted_and_blank_dropped():
    d = dispute(("2026-03", " ", "2026-01"))
    assert disputed_months(d, {"2026-02", "2026-03", ""}) == ["2026-01", "2026-02", "2026-03"]
    assert disputed_months(dispute(()), set()) == []
    assert disputed_months(dispute(("March 2026",)), set()) == ["March 2026"]   # kept -> NO_DATA, fail safe


def test_window_is_union_of_plus_minus_two():
    assert shift_month("2026-01", -2) == "2025-11" and shift_month("2025-12", 2) == "2026-02"
    w = window_months(["2025-01", "2026-06", "bad"])
    assert w == {"2024-11", "2024-12", "2025-01", "2025-02", "2025-03",
                 "2026-04", "2026-05", "2026-06", "2026-07", "2026-08"}


def test_gather_evidence_ids_window_hash_and_minimisation():
    cycles = [cyc(f"2026-{m:02d}", 0, "PH_R0_CURRENT") for m in range(1, 13)]
    acct = account(cycles, notes=[{"note_id": "N7", "type": "OTHER", "start_date": "2026-01-01", "end_date": None}],
                   ft=[{"note_id": "F1", "text": "x"}],
                   txns=[{"txn_id": "T1", "posted_date": "2026-05-10", "amount": 5, "type": "PAYMENT"},
                         {"txn_id": "T2", "posted_date": "2026-09-10", "amount": 5, "type": "PAYMENT"}])
    att = Attachment("A1", "l.pdf", "application/pdf", 1, "text", "sha", {"author": "x"})
    ev = gather_evidence(dispute(("2026-05",), (att,)), FakeSor([acct]), ["2026-05"], NOW)
    ids = [e.evidence_id for e in ev]
    assert ids == ["EV-ACDV", "EV-ATT-A1", "EV-ACCOUNT", "EV-PROFILE", "EV-CYCLE-2026-03", "EV-CYCLE-2026-04",
                   "EV-CYCLE-2026-05", "EV-CYCLE-2026-06", "EV-CYCLE-2026-07", "EV-NOTE-1", "EV-FTNOTE-1"]
    by = {e.evidence_id: e for e in ev}
    for e in ev:
        assert e.sha256 == sha256_hex(canonical(e.content)) and e.retrieved_at == NOW
        json.dumps(e.content)   # JSON-serialisable
    assert by["EV-ACCOUNT"].source == "mock_sor" and by["EV-ACDV"].source == "acdv"
    assert "ssn" not in json.dumps(by["EV-ACCOUNT"].content) and "dob" not in by["EV-ACCOUNT"].content["consumer"]
    assert "cycles" not in by["EV-ACCOUNT"].content
    assert [t["txn_id"] for t in by["EV-CYCLE-2026-05"].content["ledger_transactions"]] == ["T1"]
    assert len(by["EV-PROFILE"].content["profile"]) == 12
    assert by["EV-NOTE-1"].content["note_id"] == "N7"
    assert by["EV-ATT-A1"].content["extracted_text"] == "text"


def test_gather_evidence_missing_account_returns_acdv_only():
    ev = gather_evidence(dispute(), FakeSor([]), ["2026-03"], NOW)
    assert [e.evidence_id for e in ev] == ["EV-ACDV"]
    comps = compare_months(["2026-03"], ev)
    assert comps[0].result == MonthResult.NO_DATA


def test_hash_changes_with_content():
    a = gather_evidence(dispute(), FakeSor([account([cyc("2026-03", 0, "PH_R0_CURRENT")])]), ["2026-03"], NOW)
    b = gather_evidence(dispute(), FakeSor([account([cyc("2026-03", 31, "PH_R0_CURRENT")])]), ["2026-03"], NOW)
    ha = {e.evidence_id: e.sha256 for e in a}
    hb = {e.evidence_id: e.sha256 for e in b}
    assert ha["EV-CYCLE-2026-03"] != hb["EV-CYCLE-2026-03"] and ha["EV-ACDV"] == hb["EV-ACDV"]


def test_real_fixture_record_shape():
    sor = MockSystemOfRecord(FIX / "sor_accounts.jsonl")
    d = next(iter(FixtureAcdvSource(FIX / "acdvs.jsonl").fetch()))
    ms = disputed_months(d, set()) or ["2026-01"]
    ev = gather_evidence(d, sor, ms, NOW)
    assert ev[0].evidence_id == "EV-ACDV"


# ------------------------------------------------------------------ R-09
def test_expected_rating_buckets():
    assert expected_rating(0) == "PH_R0_CURRENT" and expected_rating(29) == "PH_R0_CURRENT"
    assert expected_rating(30) == "PH_R30" and expected_rating(41) == "PH_R30" and expected_rating(180) == "PH_R180P"
    assert expected_rating(-1) is None and expected_rating(None) is None and expected_rating(True) is None


def test_compare_match_mismatch_nodata():
    acct = account([cyc("2026-01", 41, "PH_R30"), cyc("2026-02", 0, "PH_R30"),
                    {"cycle_month": "2026-03", "dpd_at_cycle": None, "reported_rating": "PH_R0_CURRENT"}])
    ev = gather_evidence(dispute(), FakeSor([acct]), ["2026-01", "2026-02", "2026-03", "2026-04"], NOW)
    r = {c.month: c for c in compare_months(["2026-04", "2026-01", "2026-02", "2026-03"], ev)}
    assert r["2026-01"].result == MonthResult.MATCH and r["2026-01"].evidence_ids == ("EV-CYCLE-2026-01",)
    assert r["2026-02"].result == MonthResult.MISMATCH and r["2026-02"].expected_rating == "PH_R0_CURRENT"
    assert r["2026-03"].result == MonthResult.NO_DATA
    assert r["2026-04"].result == MonthResult.NO_DATA and r["2026-04"].evidence_ids == ("EV-ACCOUNT",)


def test_duplicate_cycle_rows_are_nodata_and_conflict():
    acct = account([cyc("2026-03", 0, "PH_R0_CURRENT"), cyc("2026-03", 45, "PH_R30")])
    dec, comps, _ = run(acct)
    assert comps[0].result == MonthResult.NO_DATA
    assert dec.outcome == Outcome.ESCALATED
    assert {ER.EVIDENCE_MISSING, ER.EVIDENCE_CONFLICT} <= set(dec.escalation_reasons)


# ------------------------------------------------------------------ R-10 / PRD §6 acceptance
def test_ac_verify_cites_rule_version_and_evidence():
    # PRD §6: SoR reports 41 DPD at the March 2026 cycle; reported 30-day late; claim contradicted.
    dec, comps, _ = run(account([cyc("2026-03", 41, "PH_R30")]))
    assert dec.outcome == Outcome.VERIFIED_AS_REPORTED and dec.escalation_reasons == () and dec.corrections == ()
    f = firing_for(dec, "VERIFIED_AS_REPORTED")
    assert f[0].rule_id == "R-10.OUTCOME" and f[0].rule_version == RULES_VERSION == dec.rules_version
    assert "EV-CYCLE-2026-03" in f[0].evidence_ids
    assert dec.table_versions["payment_rating_map"] == {"version": "0.1.0", "verified": False}


def test_ac_one_mismatch_modify_that_month_only():
    acct = account([cyc("2026-02", 0, "PH_R0_CURRENT"), cyc("2026-03", 0, "PH_R30")])
    dec, _, _ = run(acct, months=("2026-02", "2026-03"),
                    claims=[claim(finding=ClaimFinding.SUPPORTED)])   # supported claim + mismatch -> MODIFY
    assert dec.outcome == Outcome.MODIFY and dec.escalation_reasons == ()
    assert [(c.month, c.field, c.reported, c.corrected) for c in dec.corrections] == \
        [("2026-03", "payment_rating", "PH_R30", "PH_R0_CURRENT")]
    assert firing_for(dec, "MODIFY")[0].evidence_ids == ("EV-CYCLE-2026-03",)


def test_ac_mismatch_plus_nodata_escalates_evidence_missing_shows_mismatch():
    acct = account([cyc("2026-03", 0, "PH_R30")])
    dec, _, _ = run(acct, months=("2026-03", "2026-04"))
    assert dec.outcome == Outcome.ESCALATED and dec.escalation_reasons == (ER.EVIDENCE_MISSING,)
    assert dec.corrections == ()
    notes = [f for f in dec.firings if f.rule_id == "R-09.MISMATCH"]
    assert notes and "2026-03" in notes[0].detail and notes[0].evidence_ids == ("EV-CYCLE-2026-03",)


@pytest.mark.parametrize("ntype", ["DEFERRAL", "HARDSHIP", "FORBEARANCE"])
def test_ac_conflict_note_overlapping_escalates(ntype):
    acct = account([cyc("2026-03", 41, "PH_R30")],
                   notes=[{"note_id": "N1", "type": ntype, "start_date": "2026-03-31", "end_date": "2026-05-31"}])
    dec, _, _ = run(acct)
    assert dec.outcome == Outcome.ESCALATED and dec.escalation_reasons == (ER.EVIDENCE_CONFLICT,)
    f = firing_for(dec, "EVIDENCE_CONFLICT")[0]
    assert f.evidence_ids == ("EV-NOTE-1", "EV-CYCLE-2026-03") and f.rule_version == RULES_VERSION


@pytest.mark.parametrize("note", [
    {"type": "DEFERRAL", "start_date": "2026-04-01", "end_date": "2026-05-31"},   # near miss after
    {"type": "HARDSHIP", "start_date": "2025-12-01", "end_date": "2026-02-28"},   # near miss before
    {"type": "PRIOR_DISPUTE", "start_date": "2026-03-01", "end_date": "2026-03-31"},
    {"type": "OTHER", "start_date": "2026-01-01", "end_date": None},
])
def test_non_overlapping_or_non_conflict_notes_do_not_block_verify(note):
    dec, _, _ = run(account([cyc("2026-03", 41, "PH_R30")], notes=[note]))
    assert dec.outcome == Outcome.VERIFIED_AS_REPORTED


@pytest.mark.parametrize("note,expect", [
    ({"start_date": "2026-03-31", "end_date": "2026-03-31"}, True),
    ({"start_date": "2026-01-01", "end_date": "2026-03-01"}, True),
    ({"start_date": "2026-04-01", "end_date": "2026-04-30"}, False),
    ({"start_date": "2026-02-01", "end_date": None}, True),      # open-ended
    ({"start_date": "2026-04-01", "end_date": None}, False),
    ({"start_date": None, "end_date": "2026-01-01"}, True),      # fail safe
    ({"start_date": "2026-03-05", "end_date": "garbage"}, True),
    ({"start_date": "2026-03-05", "end_date": "2026-03-01"}, True),
])
def test_note_overlap_definition(note, expect):
    assert note_overlaps(note, "2026-03")[0] is expect


def test_unknown_note_type_fails_safe():
    dec, _, _ = run(account([cyc("2026-03", 41, "PH_R30")],
                            notes=[{"type": "PAYMENT_PLAN", "start_date": "2026-03-01", "end_date": "2026-03-02"}]))
    assert ER.EVIDENCE_CONFLICT in dec.escalation_reasons


def test_llm_note_flag_adds_conflict():
    dec, _, _ = run(account([cyc("2026-03", 41, "PH_R30")], ft=[{"note_id": "F1", "text": "x"}]), llm_flag=True)
    assert dec.escalation_reasons == (ER.EVIDENCE_CONFLICT,)
    assert firing_for(dec, "EVIDENCE_CONFLICT")[0].evidence_ids == ("EV-FTNOTE-1",)


@pytest.mark.parametrize("finding", [ClaimFinding.SUPPORTED, ClaimFinding.NOT_ADDRESSABLE, None])
def test_ac_all_match_but_claim_not_contradicted_escalates(finding):
    dec, _, _ = run(account([cyc("2026-03", 41, "PH_R30")]),
                    claims=[claim(), claim("C2", finding, ids=())])
    assert dec.outcome == Outcome.ESCALATED and dec.escalation_reasons == (ER.CLAIM_UNRESOLVED,)
    assert "C2=" in firing_for(dec, "CLAIM_UNRESOLVED")[0].detail


@pytest.mark.parametrize("ids", [(), ("EV-NOPE",)])
def test_contradicted_without_valid_citation_is_unresolved(ids):
    dec, _, _ = run(account([cyc("2026-03", 41, "PH_R30")]), claims=[claim(ids=ids)])
    assert dec.escalation_reasons == (ER.CLAIM_UNRESOLVED,)


def test_ac_no_months_escalates_months_undetermined():
    dec, _, _ = run(account([cyc("2026-03", 41, "PH_R30")]), months=(), claims=[claim(months=())])
    assert dec.outcome == Outcome.ESCALATED and dec.escalation_reasons == (ER.MONTHS_UNDETERMINED,)
    assert firing_for(dec, "MONTHS_UNDETERMINED")[0].rule_id == "R-08.MONTHS_UNDETERMINED"


def test_missing_account_escalates_evidence_missing():
    dec, _, _ = run(None)
    assert dec.escalation_reasons == (ER.EVIDENCE_MISSING,)


def test_all_reasons_recorded_with_upstream():
    acct = account([cyc("2026-03", 0, "PH_R30")],
                   notes=[{"type": "HARDSHIP", "start_date": "2026-03-01", "end_date": "2026-03-31"}])
    dec, _, _ = run(acct, months=("2026-03", "2026-04"), upstream=(ER.BREACHED, ER.DOC_UNREADABLE), llm_flag=True)
    assert dec.escalation_reasons == (ER.DOC_UNREADABLE, ER.BREACHED, ER.EVIDENCE_MISSING, ER.EVIDENCE_CONFLICT)
    for r in dec.escalation_reasons:
        assert firing_for(dec, r.value)
    assert firing_for(dec, "BREACHED")[0].rule_id == "R-05.BREACHED"


def test_upstream_escalation_forces_escalated_even_if_clean():
    for r in ER:
        dec, _, _ = run(account([cyc("2026-03", 41, "PH_R30")]), upstream=(r,))
        assert dec.outcome == Outcome.ESCALATED and r in dec.escalation_reasons


@pytest.mark.parametrize("cats,route,outcome,reason", [
    ({Category.BALANCE}, Route.OUT_OF_SCOPE, Outcome.OUT_OF_SCOPE, None),
    ({Category.OTHER}, Route.OUT_OF_SCOPE, Outcome.OUT_OF_SCOPE, None),
    ({Category.IDENTITY_FRAUD}, Route.ESCALATE_FRAUD, Outcome.ESCALATED, ER.ID_FRAUD_SUSPECTED),
    ({Category.PAYMENT_HISTORY, Category.BALANCE}, Route.ESCALATE_MULTI_ISSUE, Outcome.ESCALATED, ER.MULTI_ISSUE),
    ({Category.PAYMENT_HISTORY, Category.BALANCE}, Route.INVESTIGATE, Outcome.ESCALATED, ER.MULTI_ISSUE),
    ({Category.UNCERTAIN}, Route.INVESTIGATE, Outcome.ESCALATED, ER.CLASS_CONFLICT),
    (set(), Route.OUT_OF_SCOPE, Outcome.ESCALATED, ER.CLASS_CONFLICT),
    ({Category.PAYMENT_HISTORY}, Route.OUT_OF_SCOPE, Outcome.ESCALATED, ER.CLASS_CONFLICT),
    ({Category.PAYMENT_HISTORY}, Route.ESCALATE_CLASS_CONFLICT, Outcome.ESCALATED, ER.CLASS_CONFLICT),
    ({Category.BALANCE}, Route.INVESTIGATE, Outcome.ESCALATED, ER.CLASS_CONFLICT),
])
def test_categories_other_than_ph_never_verify(cats, route, outcome, reason):
    cls = replace(PH, categories=frozenset(cats), route=route)
    dec, _, _ = run(account([cyc("2026-03", 41, "PH_R30")]), cls=cls)
    assert dec.outcome == outcome
    if reason:
        assert reason in dec.escalation_reasons


def test_never_delete_even_when_letter_asks():
    dec, _, _ = run(account([cyc("2026-03", 0, "PH_R30")]))
    assert dec.outcome == Outcome.MODIFY
    assert all(f.result != "DELETE" for f in dec.firings)
