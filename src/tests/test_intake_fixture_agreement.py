"""Agreement of intake outputs with generator-intent labels on seed20261019_n200 (synthetic).

Labels are generator intent (circular with the PRD rules, U20/U31); they are read here only to
measure agreement, never by production code. `now` = fixture_meta.ingest_date at 17:00 New York.

Two mappings are measured:
- current: `acdv_to_dispute` as on main. Known disagreement: 4 `malformed:blank_last_name` cases,
  because the mapper turns a blank last name into a one-word consumer_name (contract issue).
- proposed: the two mapper changes requested in docs/engineering/stage-notes/intake.md.
"""
import json
from datetime import date
from pathlib import Path

import pytest

from disputes.config import defaults
from disputes.domain import SuspicionLevel
from disputes.intake.dedup import find_repeat
from disputes.intake.service import code_categories, run_intake
from test_intake_helpers import dispute_from_envelope, eod

FIX = Path(__file__).resolve().parents[1] / "data" / "fixtures" / "seed20261019_n200"
INTAKE_REASONS = {"INTAKE_INVALID", "DOC_UNREADABLE", "BREACHED"}
CFG = defaults()


@pytest.fixture(scope="module")
def cases():
    labels = {json.loads(l)["case_id"]: json.loads(l) for l in (FIX / "labels.jsonl").open()}
    envs = [json.loads(l) for l in (FIX / "acdvs.jsonl").open() if l.strip()]
    return [(e, labels[e["case_id"]]) for e in envs]


def evaluate(cases, proposed):
    rows = []
    for env, lab in cases:
        if lab["gold"]["outcome"] == "DUPLICATE_IGNORED":
            continue                     # duplicates are decided by the workflow DB lookup, not intake
        d = dispute_from_envelope(env, proposed_contract=proposed)
        r, s = run_intake(d, eod(env["fixture_meta"]["ingest_date"]), CFG, [])
        gold_clock = lab["gold"]["clock_state_at_intake"]
        rows.append({
            "case_id": env["case_id"], "lab": lab,
            "reasons_ok": {x.value for x in r.escalations} == INTAKE_REASONS & set(lab["gold"]["escalation_reasons"]),
            # gold clock is null for INTAKE_INVALID cases (not evaluated); we still compute it when the due date parses
            "clock_ok": gold_clock is None or (r.clock is not None and r.clock.state.value == gold_clock),
            "susp_ok": s.level.value == lab["suspicious_expected"],
            "level": s.level, "findings": r.attachment_findings,
        })
    return rows


def test_agreement_current_mapping(cases):
    rows = evaluate(cases, proposed=False)
    assert len(rows) == 196
    bad = [r for r in rows if not (r["reasons_ok"] and r["clock_ok"] and r["susp_ok"])]
    # Every disagreement is the known contract issue, nothing else.
    assert {tuple(r["lab"]["other_tags"]) for r in bad} == {("malformed:blank_last_name",)}
    assert len(bad) == 4
    assert all(r["clock_ok"] and r["susp_ok"] for r in rows)


def test_agreement_proposed_mapping_is_total(cases):
    rows = evaluate(cases, proposed=True)
    assert [r["case_id"] for r in rows if not r["reasons_ok"]] == []
    assert [r["case_id"] for r in rows if not r["clock_ok"]] == []
    assert [r["case_id"] for r in rows if not r["susp_ok"]] == []
    clocks = [r["lab"]["gold"]["clock_state_at_intake"] for r in rows]
    assert clocks.count("AT_RISK") == 4 and clocks.count("BREACHED") == 4     # the states were actually exercised


def test_hidden_text_finding_matches_injection_tag(cases):
    rows = evaluate(cases, proposed=True)
    for r in rows:
        hidden = any(f.hidden_text for f in r["findings"])
        assert hidden == ("injection_hidden_text" in r["lab"]["adversarial_tags"]), r["case_id"]


def test_false_positive_rate_on_clean_cases(cases):
    """B14 / U23: HIGH (and any) flags on clean cases. Target <=5%."""
    rows = evaluate(cases, proposed=False)
    clean = [r for r in rows if r["lab"]["suspicious_expected"] == "NONE"]
    high = sum(r["level"] == SuspicionLevel.HIGH for r in clean)
    anyflag = sum(r["level"] != SuspicionLevel.NONE for r in clean)
    assert len(clean) == 188
    assert high / len(clean) <= 0.05 and anyflag == 0
    controls = [r for r in clean if "imperative_negative_control" in r["lab"]["other_tags"]]
    assert controls and all(r["level"] == SuspicionLevel.NONE for r in controls)


def test_repeat_agreement(cases):
    """Replay the fixtures in ingest order as if each became a case; repeat key = account + code category."""
    order = sorted(range(len(cases)), key=lambda i: (cases[i][0]["fixture_meta"]["ingest_date"], i))
    made, seen, agree, n = [], set(), 0, 0
    for i in order:
        env, lab = cases[i]
        a = env["acdv"]
        cn = a.get("control_number")
        if cn in seen:
            continue
        seen.add(cn)
        received = date.fromisoformat(a["date_received"])
        prior = sorted((c for c in made if c["account"] == a.get("account_number")),
                       key=lambda c: c["date_received"], reverse=True)
        hit = find_repeat(date_received=received, categories=code_categories(a.get("dispute_codes")),
                          prior_cases=prior, window_days=CFG.repeat_window_days)
        n += 1
        agree += (hit["case_id"] if hit else None) == lab["repeat_of"]
        made.append({"case_id": cn, "account": a.get("account_number"), "date_received": received,
                     "categories": sorted(code_categories(a.get("dispute_codes")))})
    assert n == 196 and agree == n
    assert sum(1 for _, lab in cases if lab["repeat_of"] and lab["duplicate_of"] is None) == 4
