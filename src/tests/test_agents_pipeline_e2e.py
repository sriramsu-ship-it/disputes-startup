"""End to end: the real pipeline (workflow.default_deps) with the OFFLINE agents backend over the
200 committed fixtures. Measures what the agents module contributes once wired; outcome
agreement also depends on intake and rules. Labels are read by this test only.
Run the report: cd src && python -m pytest -q tests/test_agents_pipeline_e2e.py -s
"""
from __future__ import annotations

import json
from collections import Counter
from datetime import datetime, timezone

from disputes.agents.llm import OfflineLlmClient
from disputes.config import defaults
from disputes.contracts_bridge import MockSystemOfRecord, acdv_to_dispute
from disputes.db import repo
from disputes.workflow import pipeline
from test_agents_helpers import FIXTURES


def _final(conn, tenant, res):
    if res.case_id is None:
        return "DUPLICATE_IGNORED", set()
    case = repo.get_case(conn, tenant_id=tenant, case_id=res.case_id)
    reasons = set(case.get("escalation_reasons") or [])
    if res.state == "ESCALATED":
        return "ESCALATED", reasons
    if res.state == "OUT_OF_SCOPE":
        return "OUT_OF_SCOPE", reasons
    return str(case.get("proposed_outcome") or res.state), reasons


def test_pipeline_with_offline_agents_on_200_fixtures(conn, tenant):
    cfg = defaults()
    sor = MockSystemOfRecord(FIXTURES / "sor_accounts.jsonl")
    deps = pipeline.default_deps(sor, OfflineLlmClient(), cfg)
    envs = [json.loads(l) for l in (FIXTURES / "acdvs.jsonl").read_text().splitlines() if l.strip()]
    labels = [json.loads(l) for l in (FIXTURES / "labels.jsonl").read_text().splitlines() if l.strip()]
    order = sorted(range(len(envs)), key=lambda i: (envs[i]["fixture_meta"]["ingest_date"], i))
    c = Counter()
    mism = []
    for i in order:
        env, lab = envs[i], labels[i]
        d = acdv_to_dispute(env)
        now = datetime.fromisoformat(env["fixture_meta"]["ingest_date"]).replace(hour=12, tzinfo=timezone.utc)
        res = pipeline.process_dispute(conn, tenant_id=tenant, dispute=d, deps=deps, cfg=cfg, now=now)
        got, reasons = _final(conn, tenant, res)
        gold = lab["gold"]["outcome"]
        c["cases"] += 1
        c["outcome_agree"] += got == gold
        c["llm_unavailable"] += "LLM_UNAVAILABLE" in reasons
        c["draft_invalid"] += "DRAFT_INVALID" in reasons
        c["system_error"] += "SYSTEM_ERROR" in reasons
        if gold == "ESCALATED" and got == "ESCALATED":
            c["gold_escalated"] += 1
            c["escalation_reason_exact"] += reasons == set(lab["gold"]["escalation_reasons"])
        elif gold == "ESCALATED":
            c["gold_escalated"] += 1
        if gold != "VERIFIED_AS_REPORTED" and got == "VERIFIED_AS_REPORTED":
            c["false_verify"] += 1
        if got != gold:
            mism.append((lab["case_id"], lab["scenario"], gold, got, sorted(reasons)))
    print(json.dumps({**c, "mismatches": mism}, indent=1))
    assert c["cases"] == 200
    assert c["llm_unavailable"] == 0 and c["system_error"] == 0
    assert c["false_verify"] == 0                   # B2 direction on fixtures (not a T1 claim)
    assert c["outcome_agree"] / c["cases"] >= 0.95  # floor set below the measured value (see notes)
