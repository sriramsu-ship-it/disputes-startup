"""R-20 response package builder. OWNER: package agent.

`build_package` returns the immutable dict that `actions._finalise` hands to the ResponseSink and
stores as the `package` artifact. It is a pure function of the case bundle, the working decision
and the approvals (plus `now`), so it can be unit-tested without a database.

Schema policy
- `package_schema_version` is bumped on any change to the meaning or shape of a key. Keys from
  v1 (the web module's first package) are kept unchanged at the top level so older readers work.
- The schema is a PLACEHOLDER. Field names are neutral labels chosen by us. They are NOT e-OSCAR
  ACDV response field names or Metro 2 field names, except `dfAuthorizedName`, which e-OSCAR's
  April 2026 release notes name as required (PRD R-20, A-grade). No e-OSCAR response code is
  mapped: the code list is not public (U6). `schema_status` says this on the face of every package.
"""
from __future__ import annotations

from datetime import date, datetime, timezone

from disputes.domain import ArtifactKind, Outcome, ReviewAction
from disputes.web import casedata as cd

PACKAGE_SCHEMA_VERSION = "placeholder-response-package-2.0"
SCHEMA_STATUS = {
    "placeholder": True,
    "validated_against_e_oscar_acdv_response": False,
    "validated_against_metro2": False,
    "response_code_mapped": False,
    "note": ("Synthetic demonstration. Placeholder schema: field names are neutral labels, not e-OSCAR or "
             "Metro 2 field names (except dfAuthorizedName). The real ACDV response layout, response codes and "
             "Metro 2 field values are proprietary and unverified (U6). Payment-rating values are invented "
             "placeholder codes. Nothing was sent to any bureau or consumer."),
}
REOPEN = ReviewAction.REOPEN_AFTER_SUBMISSION.value
FIELD_PAYMENT_RATING = "payment_rating"


def _iso_date(v) -> date | None:
    if isinstance(v, date) and not isinstance(v, datetime):
        return v
    if isinstance(v, datetime):
        return v.date()
    try:
        return date.fromisoformat(str(v)[:10]) if v else None
    except ValueError:
        return None


def _ts(v) -> str | None:
    if v is None:
        return None
    return v.astimezone(timezone.utc).isoformat() if isinstance(v, datetime) else str(v)


def month_by_month(comparison: list[dict], corrections: list[dict], outcome: str | None) -> list[dict]:
    """One row per month: what was reported, what the system of record supports, what we return.

    `response_value` is the reported value unless a correction exists for that month (MODIFY);
    for DELETE it is None (the whole tradeline is the subject of the response)."""
    corr = {(c.get("month"), c.get("field") or FIELD_PAYMENT_RATING): c for c in corrections or []}
    rows, seen = [], set()
    for m in comparison or []:
        key = (m.get("month"), FIELD_PAYMENT_RATING)
        seen.add(key)
        c = corr.get(key)
        reported = m.get("reported_rating")
        rows.append({
            "month": m.get("month"), "field": FIELD_PAYMENT_RATING, "reported": reported,
            "system_of_record_value": m.get("expected_rating"), "days_past_due": m.get("dpd"),
            "comparison_result": m.get("result"), "evidence_ids": list(m.get("evidence_ids") or []),
            "response_value": None if outcome == Outcome.DELETE.value else (c["corrected"] if c else reported),
            "changed": bool(c) and c.get("corrected") != reported,
        })
    for key, c in sorted(corr.items(), key=lambda kv: (str(kv[0][0]), str(kv[0][1]))):
        if key in seen:
            continue
        rows.append({"month": c.get("month"), "field": c.get("field") or FIELD_PAYMENT_RATING,
                     "reported": c.get("reported"), "system_of_record_value": None, "days_past_due": None,
                     "comparison_result": None, "evidence_ids": [],
                     "response_value": None if outcome == Outcome.DELETE.value else c.get("corrected"),
                     "changed": c.get("corrected") != c.get("reported")})
    return sorted(rows, key=lambda r: str(r["month"]))


def _approvals_with_times(b: cd.CaseBundle, approvals: list[dict]) -> list[dict]:
    """Attach each approver's decision time from the review records (newest matching row)."""
    out = []
    for a in approvals:
        want = ReviewAction.SECOND_APPROVE.value if a.get("stage") == "second" else ReviewAction.APPROVE.value
        row = next((r for r in reversed(b.reviews) if r["data"].get("action") == want
                    and r["data"].get("actor_id") == a.get("user_id")), None)
        out.append({**a, "at": _ts(row["created_at"]) if row else None})
    return out


def build_package(b: cd.CaseBundle, w: dict, *, approvals: list[dict], authorised_name: str, versions: dict,
                  now: datetime | None = None) -> dict:
    case = b.case
    now = now or datetime.now(timezone.utc)
    prev = b.packages[-1] if b.packages else None
    change_reason = None
    if prev is not None:
        reopen = next((r["data"] for r in reversed(b.reviews) if r["data"].get("action") == REOPEN), None) or {}
        change_reason = {"reason_code": reopen.get("reason_code"), "reason_text": reopen.get("reason_text"),
                         "reopened_by": reopen.get("actor_id")}
    sents = cd.narrative_sentences(b, w)
    dispute = b.get(ArtifactKind.DISPUTE) or {}
    decision = b.get(ArtifactKind.DECISION) or {}
    due, target, received = (_iso_date(case.get("response_due_date")), _iso_date(case.get("internal_target_date")),
                             _iso_date(case.get("date_received")))
    days_before_due = (due - now.date()).days if due else None
    claims = cd.effective_claims(b, w)
    acct = case.get("account_number") or ""
    return {
        "package_schema_version": PACKAGE_SCHEMA_VERSION,
        "schema_status": dict(SCHEMA_STATUS),
        # --- v1 keys (unchanged meaning) ---
        "package_version": len(b.packages) + 1,
        "tenant_id": case["tenant_id"], "case_id": case["case_id"], "channel": case["channel"],
        "control_number": case["control_number"], "cra": case["cra"], "account_number": acct,
        "outcome": w["outcome"], "corrections": w["corrections"],
        "narrative": " ".join(s["text"] for s in sents), "narrative_sentences": sents,
        "dfAuthorizedName": authorised_name,
        "approvals": _approvals_with_times(b, approvals),
        "versions": versions,
        "supersedes_package_sha256": prev["data_sha256"] if prev else None,
        "change_reason": change_reason,
        "synthetic": bool(case.get("synthetic", True)) and bool(dispute.get("synthetic", True)),
        # --- v2 additions ---
        "account_last4": case.get("account_last4") or acct[-4:],
        "dispute": {"dispute_codes": list(dispute.get("dispute_codes") or []),
                    "disputed_months": list(dispute.get("disputed_months") or []),
                    "categories": list(case.get("categories") or [])},
        "month_by_month": month_by_month(b.get(ArtifactKind.COMPARISON) or [], w["corrections"], w["outcome"]),
        "basis": {
            "proposed_outcome": cd.proposal(b)["outcome"],
            "departs_from_proposal": cd.departs_from_proposal(b, w),
            "rules_version": decision.get("rules_version"),
            "rule_firings": [{"rule_id": f.get("rule_id"), "rule_version": f.get("rule_version"),
                              "result": f.get("result"), "evidence_ids": list(f.get("evidence_ids") or []),
                              "detail": f.get("detail") or ""} for f in decision.get("firings") or []],
            "claims": [{"claim_id": c["claim_id"], "text": c.get("text"), "finding": c.get("finding"),
                        "finding_source": c.get("finding_source"), "evidence_ids": list(c.get("evidence_ids") or []),
                        "reason": c.get("reason") or ""} for c in claims],
            "evidence": [{"evidence_id": e["evidence_id"], "kind": e.get("kind"), "source": e.get("source"),
                          "sha256": e.get("sha256")} for e in b.evidence],
        },
        "timing": {"date_received": received.isoformat() if received else None,
                   "internal_target_date": target.isoformat() if target else None,
                   "response_due_date": due.isoformat() if due else None,
                   "finalised_at": now.astimezone(timezone.utc).isoformat(),
                   "calendar_days_before_due": days_before_due,
                   "on_or_before_due": None if days_before_due is None else days_before_due >= 0,
                   "note": "Calendar days. The business-day calendar for ACDV due dates is unverified (U21)."},
    }
