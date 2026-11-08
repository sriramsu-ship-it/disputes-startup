"""Offline-backend agreement report on the 200 committed fixtures (labels read by the TEST only).

Run the report:  cd src && python -m tests.test_agents_agreement   (prints JSON)
The asserted floors are regression guards for the offline heuristics, set a little below the
measured values recorded in docs/engineering/stage-notes/agents.md. They are NOT model-quality
claims: the offline backend is not the product's model.
"""
from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from disputes.agents.claims import extract_claims, map_claims, source_texts  # noqa: E402
from disputes.agents.classify import classify  # noqa: E402
from disputes.agents.draft import draft_narrative  # noqa: E402
from disputes.agents.llm import CaseBudget, OfflineLlmClient  # noqa: E402
from disputes.config import defaults  # noqa: E402
from disputes.domain import (Category, Correction, Decision, EscalationReason, Outcome,  # noqa: E402
                             Route, RuleFiring)
from test_agents_helpers import build_evidence, load_fixture_cases  # noqa: E402

INTAKE_ONLY = {"INTAKE_INVALID", "DOC_UNREADABLE", "BREACHED"}


def gold_route(lab) -> Route:
    cats = set(lab["categories"])
    codes = set(lab["dispute_code_categories"])
    if "IDENTITY_FRAUD" in cats or "IDENTITY_FRAUD" in codes:
        return Route.ESCALATE_FRAUD
    if cats != codes:
        return Route.ESCALATE_CLASS_CONFLICT
    if len(cats) > 1:
        return Route.ESCALATE_MULTI_ISSUE
    if cats == {"PAYMENT_HISTORY"}:
        return Route.INVESTIGATE
    return Route.OUT_OF_SCOPE


def _overlap(a, b) -> float:
    lo, hi = max(a[0], b[0]), min(a[1], b[1])
    inter = max(0, hi - lo)
    union = max(a[1], b[1]) - min(a[0], b[0])
    return inter / union if union else 0.0


def _gold_decision(lab, evidence) -> Decision:
    g = lab["gold"]
    known = {e.evidence_id for e in evidence}
    outcome = {"VERIFIED_AS_REPORTED": Outcome.VERIFIED_AS_REPORTED, "MODIFY": Outcome.MODIFY}.get(
        g["outcome"], Outcome.ESCALATED)
    reasons = tuple(EscalationReason(r) for r in g["escalation_reasons"]) if outcome == Outcome.ESCALATED else ()
    ids = tuple(f"EV-CYCLE-{m}" for m in g["disputed_months"] if f"EV-CYCLE-{m}" in known)
    return Decision(outcome=outcome, escalation_reasons=reasons,
                    corrections=tuple(Correction(c["month"], "payment_rating", c["reported_rating"],
                                                 c["corrected_rating"]) for c in g["corrections"]),
                    firings=(RuleFiring("R-10.TEST", "test", outcome.value, ids),),
                    rules_version="test")


def compute_report(cases=None) -> dict:
    cfg = defaults().with_overrides(llm_max_calls_per_case=5)   # room for the R-13 retry (see notes)
    cases = cases or load_fixture_cases()
    client = OfflineLlmClient()
    r = Counter()
    route_confusion = Counter()
    cat_miss = []
    finding_conf = Counter()
    draft_errs = Counter()
    for d, acct, lab in cases:
        b = CaseBudget(client, cfg)
        cl = classify(d, b)
        r["cases"] += 1
        r["llm_set_agree"] += set(c.value for c in cl.llm_categories) == set(lab["categories"])
        gr = gold_route(lab)
        r["route_agree"] += cl.route == gr
        route_confusion[(gr.value, cl.route.value)] += 1
        if cl.route != gr:
            cat_miss.append(lab["case_id"])
        fraud_gold = gr == Route.ESCALATE_FRAUD
        r["fraud_gold"] += fraud_gold
        r["fraud_caught"] += fraud_gold and cl.route == Route.ESCALATE_FRAUD
        r["fraud_false_pos"] += (not fraud_gold) and cl.route == Route.ESCALATE_FRAUD
        r["llm_flagged"] += b.suspicious_flag
        r["llm_flag_expected"] += lab["suspicious_expected"] != "NONE"
        r["llm_flag_hit"] += b.suspicious_flag and lab["suspicious_expected"] != "NONE"
        # ---- claims (run on every case so recall is measured on all labelled claims)
        claims, esc = extract_claims(d, b)
        r["claims_extracted"] += len(claims)
        r["claims_located"] += sum(c.span is not None for c in claims)
        r["quote_unlocated_cases"] += bool(esc)
        gold_claims = lab["claims"]
        r["gold_claims"] += len(gold_claims)
        matched = {}
        for gc in gold_claims:
            best, best_ov = None, 0.0
            for c in claims:
                if c.span and c.source_id == gc["source"]:
                    ov = _overlap(c.span, tuple(gc["span"]))
                    if ov > best_ov:
                        best, best_ov = c, ov
            r["gold_claims_any_overlap"] += best is not None and best_ov > 0
            r["gold_claims_matched"] += best_ov >= 0.5
            r["gold_claims_exact"] += best_ov == 1.0
            if best_ov >= 0.5:
                matched[gc["claim_id"]] = best
                r["months_agree"] += sorted(best.months) == sorted(gc["months"])
                r["type_agree"] += best.claim_type == gc["claim_type"]
        gold_spans = [tuple(gc["span"]) for gc in gold_claims]
        r["extra_claims"] += sum(1 for c in claims if not c.span or
                                 all(_overlap(c.span, s) < 0.5 for s in gold_spans))
        # ---- mapping: evidence built from the SoR for ACDV months ∪ claim months
        months = sorted(set(d.disputed_months) | {m for c in claims for m in c.months})
        ev = build_evidence(d, acct, months)
        mapped, uesc = map_claims(claims, ev, b)
        r["unaddressed_cases"] += bool(uesc)
        by_id = {c.claim_id: c for c in mapped}
        for gc in gold_claims:
            c = matched.get(gc["claim_id"])
            if c is None:
                continue
            mc = by_id[c.claim_id]
            f = mc.finding.value if mc.finding else "NONE"
            finding_conf[(gc["finding"], f)] += 1
            r["findings_scored"] += 1
            r["finding_agree"] += f == gc["finding"]
            basis = gc["evidence_basis"]
            if basis.startswith("cycle:") and gc["finding"] == f and f != "NOT_ADDRESSABLE":
                r["cycle_basis_scored"] += 1
                r["cycle_basis_cited"] += f"EV-CYCLE-{basis[6:]}" in mc.evidence_ids
        # ---- draft on cases the pipeline would draft (in-scope, not fraud/OOS, not duplicate)
        if lab["gold"]["outcome"] in ("VERIFIED_AS_REPORTED", "MODIFY", "ESCALATED") and gr == Route.INVESTIGATE:
            dec = _gold_decision(lab, ev)
            dr = draft_narrative(dec, mapped, ev, b, source_texts=source_texts(d))
            r["drafts"] += 1
            r["drafts_valid"] += dr.valid
            r["drafts_valid_first_try"] += dr.valid and dr.attempts == 1
            for e in dr.validator_errors:
                draft_errs[e.split(":")[0]] += 1
        r["calls"] += b.calls_made
        r["max_calls_case"] = max(r["max_calls_case"], b.calls_made)
        r["cost_usd"] += b.cost_usd
    rep = dict(r)
    rep["route_confusion"] = {f"{k[0]}->{k[1]}": v for k, v in sorted(route_confusion.items())}
    rep["finding_confusion"] = {f"{k[0]}->{k[1]}": v for k, v in sorted(finding_conf.items())}
    rep["draft_error_codes"] = dict(draft_errs)
    rep["route_mismatch_cases"] = cat_miss
    return rep


_REPORT = None


def _report():
    global _REPORT
    if _REPORT is None:
        _REPORT = compute_report()
    return _REPORT


def test_report_runs_on_all_200_fixtures():
    rep = _report()
    assert rep["cases"] == 200
    assert rep["gold_claims"] > 0


def test_routing_agreement_floor():
    rep = _report()
    assert rep["route_agree"] / rep["cases"] >= 0.95


def test_no_missed_fraud_on_fixtures():
    rep = _report()
    assert rep["fraud_caught"] == rep["fraud_gold"]


def test_claim_extraction_floor():
    rep = _report()
    assert rep["claims_located"] == rep["claims_extracted"]          # offline quotes are verbatim
    assert rep["gold_claims_matched"] / rep["gold_claims"] >= 0.95


def test_finding_agreement_floor():
    rep = _report()
    assert rep["finding_agree"] / rep["findings_scored"] >= 0.90


def test_draft_validity_floor():
    rep = _report()
    assert rep["drafts"] > 0 and rep["drafts_valid"] / rep["drafts"] >= 0.95


def test_offline_cost_is_zero():
    assert _report()["cost_usd"] == 0


if __name__ == "__main__":
    print(json.dumps(compute_report(), indent=1, sort_keys=True))
