"""Rules-in-isolation agreement with the 200 committed fixture labels (seed 20261019).

CIRCULARITY (U35): the gold labels come from synthgen/oracle.py, which encodes the same PRD
rules. Agreement here is a consistency check between two implementations of one spec, not
independent evidence that the rules are right. This test reads fixtures/labels only; it does
not import synthgen.

Inputs fed to the rules (to isolate R-08/R-09/R-10 from intake, classification and claims):
- classification = {PAYMENT_HISTORY} / INVESTIGATE
- claims = gold claims from labels.jsonl (finding, months), with `evidence_basis` mapped to our
  evidence IDs ("cycle:M" -> EV-CYCLE-M, "note:<note_id>" -> EV-NOTE-<position>); claims whose
  basis is a free-text reason get no evidence IDs.
- upstream_escalations = gold reasons in {BREACHED, DOC_UNREADABLE} (raised by intake, R-03/R-05;
  the oracle keeps evaluating the rules after them, so the rules must still add their own).

Filter (cases whose gold path reaches the rules), defined on inputs, not on the gold outcome:
not a duplicate (duplicate_of is null), not INTAKE_INVALID, and categories ==
dispute_code_categories == [PAYMENT_HISTORY] (excludes ID fraud, out of scope, multi-issue and
class-conflict cases, which are decided by R-02/R-07 before any evidence is gathered).
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from disputes.contracts_bridge import FixtureAcdvSource, MockSystemOfRecord
from disputes.domain import (Category, Claim, ClaimFinding, Classification, EscalationReason, Route)
from disputes.rules.compare import compare_months
from disputes.rules.evidence import disputed_months, gather_evidence
from disputes.rules.outcome import decide

FIX = Path(__file__).resolve().parents[1] / "data" / "fixtures" / "seed20261019_n200"
NOW = datetime(2026, 10, 9, 12, 0, tzinfo=timezone.utc)
UPSTREAM = {"BREACHED", "DOC_UNREADABLE"}
CLS = Classification(frozenset({Category.PAYMENT_HISTORY}), frozenset({Category.PAYMENT_HISTORY}),
                     frozenset({Category.PAYMENT_HISTORY}), (), None, Route.INVESTIGATE)


def _load():
    labels = {}
    with (FIX / "labels.jsonl").open() as f:
        for line in f:
            if line.strip():
                lab = json.loads(line)
                labels[lab["case_id"]] = lab
    envs = [json.loads(x) for x in (FIX / "acdvs.jsonl").read_text().splitlines() if x.strip()]
    disputes = list(FixtureAcdvSource(FIX / "acdvs.jsonl").fetch())
    return labels, envs, disputes, MockSystemOfRecord(FIX / "sor_accounts.jsonl")


def reaches_rules(lab: dict) -> bool:
    return (lab["duplicate_of"] is None
            and "INTAKE_INVALID" not in lab["gold"]["escalation_reasons"]
            and lab["categories"] == ["PAYMENT_HISTORY"]
            and lab["dispute_code_categories"] == ["PAYMENT_HISTORY"])


def _claims(lab: dict, acct: dict | None) -> list[Claim]:
    note_pos = {n.get("note_id"): i for i, n in enumerate((acct or {}).get("notes") or (), start=1)}
    out = []
    for c in lab["claims"]:
        basis = c["evidence_basis"]
        ids: tuple[str, ...] = ()
        if basis.startswith("cycle:"):
            ids = (f"EV-CYCLE-{basis[6:]}",)
        elif basis.startswith("note:") and basis[5:] in note_pos:
            ids = (f"EV-NOTE-{note_pos[basis[5:]]}",)
        out.append(Claim(c["claim_id"], c["quote"], c["quote"], c["source"],
                         tuple(c["span"]) if c.get("span") else None, c["claim_type"],
                         tuple(c["months"]), ClaimFinding(c["finding"]), ids,
                         basis if c["finding"] == "NOT_ADDRESSABLE" else ""))
    return out


def run_agreement() -> dict:
    labels, envs, disputes, sor = _load()
    rows = []
    for env, d in zip(envs, disputes):
        lab = labels[env["case_id"]]
        if not reaches_rules(lab):
            continue
        acct = sor.get_account(d.account_number) if d.account_number else None
        claims = _claims(lab, acct)
        months = disputed_months(d, {m for c in claims for m in c.months})
        ev = gather_evidence(d, sor, months, NOW)
        comps = compare_months(months, ev)
        g = lab["gold"]
        upstream = tuple(EscalationReason(r) for r in g["escalation_reasons"] if r in UPSTREAM)
        dec = decide(classification=CLS, comparisons=comps, evidence=ev, claims=claims,
                     upstream_escalations=upstream)
        got = {
            "disputed_months": months,
            "month_results": {c.month: c.result.value for c in comps},
            "outcome": dec.outcome.value,
            "escalation_reasons": sorted(r.value for r in dec.escalation_reasons),
            "corrections": sorted((c.month, c.reported, c.corrected) for c in dec.corrections),
        }
        want = {
            "disputed_months": g["disputed_months"],
            "month_results": g["month_results"],
            "outcome": g["outcome"],
            "escalation_reasons": sorted(g["escalation_reasons"]),
            "corrections": sorted((c["month"], c["reported_rating"], c["corrected_rating"]) for c in g["corrections"]),
        }
        diffs = {k: (got[k], want[k]) for k in got if got[k] != want[k]}
        rows.append({"case_id": lab["case_id"], "scenario": lab["scenario"], "diffs": diffs})
    return {"n": len(rows), "agree": sum(1 for r in rows if not r["diffs"]),
            "disagreements": [r for r in rows if r["diffs"]], "rows": rows}


def test_fixture_agreement_rules_in_isolation():
    res = run_agreement()
    assert res["n"] == 148, res["n"]   # 200 - 52 excluded (see module docstring)
    # Every disagreement must be investigated and listed in docs/engineering/stage-notes/rules.md.
    assert res["disagreements"] == [], json.dumps(res["disagreements"][:5], indent=1)


def test_filter_excludes_upstream_decided_cases():
    labels, *_ = _load()
    excluded = [lab for lab in labels.values() if not reaches_rules(lab)]
    outcomes = {lab["gold"]["outcome"] for lab in excluded}
    assert "VERIFIED_AS_REPORTED" not in outcomes and "MODIFY" not in outcomes
    reasons = {r for lab in labels.values() if reaches_rules(lab) for r in lab["gold"]["escalation_reasons"]}
    assert not reasons & {"INTAKE_INVALID", "ID_FRAUD_SUSPECTED", "CLASS_CONFLICT", "MULTI_ISSUE"}


if __name__ == "__main__":   # cd src && python -m tests.test_rules_fixture_agreement
    from collections import Counter
    r = run_agreement()
    print(f"n={r['n']} agree={r['agree']}")
    print(Counter((x["scenario"], bool(x["diffs"])) for x in r["rows"]))
    for x in r["disagreements"]:
        print(x["case_id"], x["scenario"], x["diffs"])
