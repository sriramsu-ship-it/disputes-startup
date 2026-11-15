"""Unit tests (no database): package builder, month-by-month rows, integrity checks, bundle names.
Data is SYNTHETIC."""
from __future__ import annotations

import copy
from datetime import date, datetime, timezone

from disputes.audit.chain import canonical, sha256_hex
from disputes.package import build, model as pm
from disputes.package.bundle import safe_name
from disputes.web.casedata import CaseBundle

COMP = [{"month": "2026-01", "dpd": 0, "expected_rating": "PH_R0_CURRENT", "reported_rating": "PH_R0_CURRENT",
         "result": "MATCH", "evidence_ids": ["EV-CYCLE-2026-01"]},
        {"month": "2026-02", "dpd": 41, "expected_rating": "PH_R30", "reported_rating": "PH_R60",
         "result": "MISMATCH", "evidence_ids": ["EV-CYCLE-2026-02"]}]
CORR = [{"month": "2026-02", "field": "payment_rating", "reported": "PH_R60", "corrected": "PH_R30"}]
V1_KEYS = {"package_version", "tenant_id", "case_id", "channel", "control_number", "cra", "account_number", "outcome",
           "corrections", "narrative", "narrative_sentences", "dfAuthorizedName", "approvals", "versions",
           "supersedes_package_sha256", "change_reason", "synthetic"}


def _bundle(outcome="MODIFY", packages=()):
    case = {"tenant_id": "synthetic-tenant-0", "case_id": "C1", "channel": "ACDV", "control_number": "SYNCN-1",
            "cra": "SYNTH-CRA-1", "account_number": "SYNACCT0000001234", "account_last4": "1234",
            "date_received": date(2026, 11, 1), "response_due_date": date(2026, 12, 1),
            "internal_target_date": date(2026, 11, 26), "proposed_outcome": outcome, "synthetic": True,
            "categories": ["PAYMENT_HISTORY"]}
    b = CaseBundle(case=case)
    b.artifacts = {"dispute": {"synthetic": True, "dispute_codes": ["PLH-PH-01"], "disputed_months": ["2026-02"]},
                   "comparison": COMP,
                   "decision": {"outcome": outcome, "corrections": CORR if outcome == "MODIFY" else [],
                                "rules_version": "1.0.0", "firings": [{"rule_id": "R-10.MODIFY", "rule_version": "1.0.0",
                                                                        "result": "MODIFY", "evidence_ids": ["EV-CYCLE-2026-02"],
                                                                        "detail": "2026-02 MISMATCH"}]},
                   "evidence": [{"evidence_id": "EV-CYCLE-2026-02", "kind": "cycle", "source": "mock_sor", "sha256": "e" * 64}],
                   "claims": [{"claim_id": "C1", "text": "paid on time", "finding": "SUPPORTED",
                               "evidence_ids": ["EV-CYCLE-2026-02"]}],
                   "draft": {"sentences": [{"text": "We updated 2026-02.", "source": "TEMPLATE", "template_id": "T1",
                                            "evidence_ids": [], "quote_spans": []}], "valid": True}}
    b.drafts = [{"data": b.artifacts["draft"]}]
    b.packages = list(packages)
    b.reviews = [{"data": {"action": "APPROVE", "actor_id": "u-spec"},
                  "created_at": datetime(2026, 11, 20, 15, 0, tzinfo=timezone.utc)}]
    return b


def _w(outcome="MODIFY"):
    return {"outcome": outcome, "corrections": CORR if outcome == "MODIFY" else [], "claim_findings": {}, "narrative": None}


NOW = datetime(2026, 11, 20, 15, 1, tzinfo=timezone.utc)


def test_package_v2_schema_keeps_v1_keys_and_says_it_is_a_placeholder():
    p = build.build_package(_bundle(), _w(), approvals=[{"user_id": "u-spec", "role": "SPECIALIST",
                                                         "display_name": "Sam (SYNTHETIC)", "stage": "final"}],
                            authorised_name="Sam (SYNTHETIC)", versions={"rules_version": "1.0.0"}, now=NOW)
    assert V1_KEYS <= set(p)
    assert p["package_schema_version"] == build.PACKAGE_SCHEMA_VERSION
    s = p["schema_status"]
    assert s["placeholder"] is True and s["validated_against_e_oscar_acdv_response"] is False
    assert s["validated_against_metro2"] is False and s["response_code_mapped"] is False
    assert p["account_last4"] == "1234" and p["dfAuthorizedName"] == "Sam (SYNTHETIC)"
    assert p["approvals"][0]["at"].startswith("2026-11-20T15:00")
    assert p["timing"]["calendar_days_before_due"] == 11 and p["timing"]["on_or_before_due"] is True
    assert p["basis"]["rule_firings"][0]["rule_id"] == "R-10.MODIFY"
    assert p["basis"]["claims"][0]["finding"] == "SUPPORTED" and p["basis"]["departs_from_proposal"] is False
    assert p["package_version"] == 1 and p["supersedes_package_sha256"] is None and p["change_reason"] is None


def test_month_by_month_modify_marks_only_corrected_months():
    rows = build.month_by_month(COMP, CORR, "MODIFY")
    by = {r["month"]: r for r in rows}
    assert by["2026-02"]["changed"] is True and by["2026-02"]["response_value"] == "PH_R30"
    assert by["2026-02"]["reported"] == "PH_R60" and by["2026-02"]["system_of_record_value"] == "PH_R30"
    assert by["2026-01"]["changed"] is False and by["2026-01"]["response_value"] == "PH_R0_CURRENT"


def test_month_by_month_verify_delete_and_extra_correction():
    assert not any(r["changed"] for r in build.month_by_month(COMP, [], "VERIFIED_AS_REPORTED"))
    assert all(r["response_value"] is None for r in build.month_by_month(COMP, [], "DELETE"))
    extra = [{"month": "2025-12", "field": "payment_rating", "reported": "PH_R30", "corrected": "PH_R0_CURRENT"}]
    rows = build.month_by_month(COMP, extra, "MODIFY")
    assert [r["month"] for r in rows] == ["2025-12", "2026-01", "2026-02"] and rows[0]["changed"]


def test_second_version_carries_reason_and_supersedes_hash():
    prev = {"data_sha256": "f" * 64, "data": {}}
    b = _bundle(packages=[prev])
    b.reviews.append({"data": {"action": "REOPEN_AFTER_SUBMISSION", "actor_id": "u-sup1", "reason_code": "OTHER",
                               "reason_text": "new documents arrived"}, "created_at": NOW})
    p = build.build_package(b, _w(), approvals=[], authorised_name="x", versions={}, now=NOW)
    assert p["package_version"] == 2 and p["supersedes_package_sha256"] == "f" * 64
    assert p["change_reason"] == {"reason_code": "OTHER", "reason_text": "new documents arrived", "reopened_by": "u-sup1"}


def _stored(pkg):
    receipt = sha256_hex(canonical(pkg))
    data = {**pkg, "sink_receipt": receipt}
    sha = sha256_hex(canonical(data))
    ev = {"event_id": 7, "event_type": "PACKAGE_WRITTEN",
          "payload": {"package_version": pkg["package_version"], "package_sha256": sha, "content_sha256": receipt}}
    return {"data": data, "data_sha256": sha}, [ev]


def test_integrity_passes_for_an_untouched_package_and_fails_when_tampered():
    pkg = build.build_package(_bundle(), _w(), approvals=[], authorised_name="x", versions={}, now=NOW)
    row, events = _stored(pkg)
    ok = pm.package_integrity(row, events)
    assert ok["ok"] is True and ok["event_id"] == 7 and all(c["ok"] for c in ok["checks"])
    bad = copy.deepcopy(row)
    bad["data"]["outcome"] = "DELETE"                       # edited after the fact, hash left alone
    r = pm.package_integrity(bad, events)
    assert r["ok"] is False and not r["checks"][0]["ok"] and not r["checks"][2]["ok"]
    assert pm.package_integrity(row, [])["ok"] is False      # no audit event -> not trusted


def test_package_document_renders_v1_packages_without_schema():
    v1 = {"package_version": 1, "outcome": "MODIFY", "account_number": "SYNACCT0000009876",
          "corrections": CORR, "narrative_sentences": [], "approvals": [], "versions": {}}
    row, events = _stored(v1)
    doc = pm.package_document(row, events, case={"response_due_date": "2026-12-01"})
    assert doc["schema_version"].startswith("web-package-1") and doc["account_masked"] == "••••9876"
    assert doc["months"][0]["response_value"] == "PH_R30" and doc["integrity"]["ok"]


def test_safe_zip_names_strip_traversal_and_separators():
    assert safe_name("../../etc/passwd") == "etc_passwd"
    assert "/" not in safe_name("a/b\\c:d") and safe_name("") == "file"
    assert len(safe_name("x" * 500)) == 80


# R-51 / level1-demo-brief §5.2: banned claims in the package and export templates (banner text exempt)
import re  # noqa: E402
from pathlib import Path  # noqa: E402

R47 = "DEMO · Synthetic data only · Not connected to e-OSCAR or any credit bureau · Never enter real personal information"
BANNED = [r"compliant", r"compliance-ready", r"certified", r"examiner[- ]ready", r"examiner[- ]approved",
          r"regulator[- ]approved", r"bank[- ]grade", r"guarantee", r"SOC ?2",
          r"(integrated|connected|connects) (with|to) e-OSCAR", r"sent to (the )?(bureau|CRA|e-OSCAR)",
          r"submitted to (the )?(bureau|CRA|e-OSCAR)", r"\d+(\.\d+)?\s?%(\W+\w+){0,3}\W+(accura|precis|recall)"]


def test_package_and_export_templates_carry_the_banner_and_no_banned_claims():
    web = Path(__file__).resolve().parents[1] / "disputes" / "web"
    files = [web / "templates" / n for n in ("package.html", "export.html", "_package_macros.html")]
    files.append(web / "static" / "package.css")
    assert R47 in (web / "templates" / "_package_macros.html").read_text(encoding="utf-8")
    for f in files:
        text = f.read_text(encoding="utf-8").replace(R47, "")
        for pat in BANNED:
            assert not re.search(pat, text, re.IGNORECASE), (f.name, pat)
