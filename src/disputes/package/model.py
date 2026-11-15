"""Read-side models for the package document and the export's examiner summary. OWNER: package agent.

Pure functions over plain dicts (artifact rows, audit events, the export dict): no database access,
so the same code serves the HTTP routes, the zip bundle and the G5 test.
"""
from __future__ import annotations

from datetime import date, datetime

from disputes.audit.chain import canonical, sha256_hex

OUTCOME_LABELS = {
    "VERIFIED_AS_REPORTED": "Verified as reported",
    "MODIFY": "Modify (account information updated)",
    "DELETE": "Delete",
    "ESCALATED": "Escalated (no response sent)",
    "OUT_OF_SCOPE": "Out of scope (handled outside this platform)",
    None: "No outcome yet",
}
FINDING_LABELS = {"SUPPORTED": "Supported by our records", "CONTRADICTED": "Contradicted by our records",
                  "NOT_ADDRESSABLE": "Cannot be resolved from our records", None: "No valid finding"}
DECISIVE_ACTIONS = ("APPROVE", "SECOND_APPROVE", "EDIT", "ESCALATE", "MARK_OUT_OF_SCOPE", "REJECT_SECOND_APPROVAL",
                    "REOPEN_AFTER_SUBMISSION")
HASH_KEYS = ("sha256", "hash", "sink_receipt")


def outcome_label(v) -> str:
    return OUTCOME_LABELS.get(v, str(v))


def finding_label(v) -> str:
    return FINDING_LABELS.get(v, str(v))


def is_hash_key(k: str) -> bool:
    k = str(k).lower()
    return any(h in k for h in HASH_KEYS)


def _d(v) -> date | None:
    if v is None:
        return None
    if isinstance(v, datetime):
        return v.date()
    if isinstance(v, date):
        return v
    try:
        return date.fromisoformat(str(v)[:10])
    except ValueError:
        return None


# ---------------------------------------------------------------- package integrity
def package_integrity(row: dict, events: list[dict]) -> dict:
    """Recompute a stored package's hashes and compare them with its PACKAGE_WRITTEN audit event.

    row: {version, data, data_sha256 | sha256}. Returns {ok, event_id, checks: [{name, ok, detail}]}."""
    data = dict(row.get("data") if "data" in row else {k: v for k, v in row.items()
                                                         if k not in ("version", "created_at", "sha256")})
    stored = row.get("data_sha256") or row.get("sha256")
    content = {k: v for k, v in data.items() if k != "sink_receipt"}
    recomputed_artifact = sha256_hex(canonical(data))
    recomputed_content = sha256_hex(canonical(content))
    ev = next((e for e in events if e.get("event_type") == "PACKAGE_WRITTEN"
               and (e.get("payload") or {}).get("package_version") == data.get("package_version")), None)
    p = (ev or {}).get("payload") or {}
    checks = [
        {"name": "stored package hash recomputes", "ok": recomputed_artifact == stored,
         "detail": f"recomputed {recomputed_artifact[:16]}… vs stored {str(stored)[:16]}…"},
        {"name": "audit event records this package", "ok": ev is not None and p.get("package_sha256") == stored,
         "detail": f"event {ev['event_id']}" if ev else "no PACKAGE_WRITTEN event for this version"},
        {"name": "content hash matches audit event and sink receipt",
         "ok": ev is not None and p.get("content_sha256") == recomputed_content == data.get("sink_receipt"),
         "detail": f"content {recomputed_content[:16]}…"},
    ]
    return {"ok": all(c["ok"] for c in checks), "event_id": (ev or {}).get("event_id"),
            "content_sha256": recomputed_content, "checks": checks}


# ---------------------------------------------------------------- package document
def package_document(row: dict, events: list[dict], *, case: dict | None = None,
                     integrity: dict | None = None) -> dict:
    """View model for one package version. Works for v1 packages (pre-schema) too. Pass `integrity`
    computed on the unmasked row when `row` is a masked (client) copy."""
    data = row["data"] if "data" in row else row
    case = case or {}
    integ = integrity or package_integrity(row, events)
    timing = data.get("timing") or {
        "date_received": str(case.get("date_received") or "") or None,
        "response_due_date": str(case.get("response_due_date") or "") or None,
        "internal_target_date": str(case.get("internal_target_date") or "") or None,
        "finalised_at": str(row.get("created_at") or "") or None, "calendar_days_before_due": None,
        "on_or_before_due": None}
    if timing.get("calendar_days_before_due") is None and timing.get("response_due_date") and timing.get("finalised_at"):
        due, fin = _d(timing["response_due_date"]), _d(timing["finalised_at"])
        if due and fin:
            timing = {**timing, "calendar_days_before_due": (due - fin).days, "on_or_before_due": due >= fin}
    acct = str(data.get("account_number") or "")
    return {
        "pkg": data, "version": data.get("package_version"), "created_at": row.get("created_at"),
        "sha256": row.get("data_sha256") or row.get("sha256"),
        "schema_version": data.get("package_schema_version") or "web-package-1 (pre-schema)",
        "schema_status": data.get("schema_status") or {"placeholder": True, "note": "Version 1 package written "
                                                       "before the schema was versioned. Placeholder schema."},
        "outcome": data.get("outcome"), "outcome_label": outcome_label(data.get("outcome")),
        "account_masked": "••••" + (data.get("account_last4") or acct[-4:]),
        "months": data.get("month_by_month") or [
            {"month": c.get("month"), "field": c.get("field"), "reported": c.get("reported"),
             "system_of_record_value": None, "days_past_due": None, "comparison_result": None, "evidence_ids": [],
             "response_value": c.get("corrected"), "changed": True} for c in data.get("corrections") or []],
        "timing": timing, "integrity": integ, "basis": data.get("basis") or {},
    }


# ---------------------------------------------------------------- export summary (page 1)
def export_summary(ex: dict) -> dict:
    """The case summary page (R-53): what was disputed, what we looked at, what we decided, why, who
    decided, when, and whether the record can be trusted. Built only from the export dict."""
    case, decision = ex.get("case") or {}, ex.get("decision") or {}
    dispute = ex.get("dispute_as_received") or {}
    reviews = ex.get("reviews") or []
    packages = ex.get("packages") or []
    final, proposed = case.get("final_outcome"), case.get("proposed_outcome")
    last_pkg = packages[-1] if packages else None
    decided_at = (last_pkg or {}).get("created_at")
    if decided_at is None:
        decisive = [r for r in reviews if r.get("action") in ("MARK_OUT_OF_SCOPE", "ESCALATE")]
        decided_at = decisive[-1]["created_at"] if decisive else None
    due = _d(case.get("response_due_date"))
    dd = _d(decided_at)
    days_before_due = (due - dd).days if due and dd else None
    refs = ex.get("reference_tables") or {}
    unverified = sorted(k for k, v in refs.items() if isinstance(v, dict) and not v.get("verified"))
    pkg_checks = ex.get("package_integrity") or []   # computed on the unmasked record by build_export
    return {
        "disputed": {
            "channel": case.get("channel"), "cra": case.get("cra"), "control_number": case.get("control_number"),
            "account_masked": "••••" + str(case.get("account_last4") or str(case.get("account_number") or "")[-4:]),
            "dispute_codes": list(dispute.get("dispute_codes") or []),
            "disputed_months": list(dispute.get("disputed_months") or []),
            "categories": list(case.get("categories") or []),
            "consumer_statement": dispute.get("free_text"),
            "claims": len(ex.get("claims") or []), "attachments": len(ex.get("attachments") or []),
        },
        "looked_at": [{"evidence_id": e.get("evidence_id"), "kind": e.get("kind"), "source": e.get("source"),
                       "sha256": e.get("sha256")} for e in ex.get("evidence") or []]
                     + [{"evidence_id": a.get("attachment_id"), "kind": "attachment", "source": a.get("file_name"),
                         "sha256": a.get("sha256")} for a in ex.get("attachments") or []],
        "decided": {
            "final_outcome": final, "final_label": outcome_label(final) if final else "Not final",
            "proposed_outcome": proposed, "proposed_label": outcome_label(proposed),
            "state": case.get("state"),
            "corrections": (last_pkg or {}).get("corrections") or [],
            "escalation_reasons": list(case.get("escalation_reasons") or []),
            "departs_from_proposal": bool(final and proposed and final != proposed),
        },
        "why": {
            "rules_version": decision.get("rules_version"),
            "rule_firings": [{"rule_id": f.get("rule_id"), "rule_version": f.get("rule_version"),
                              "result": f.get("result"), "evidence_ids": list(f.get("evidence_ids") or []),
                              "detail": f.get("detail") or ""} for f in decision.get("firings") or []],
            "claims": [{"claim_id": c.get("claim_id"), "text": c.get("text"), "quote": c.get("quote"),
                        "source_id": c.get("source_id"), "span": c.get("span"), "finding": c.get("finding"),
                        "finding_label": finding_label(c.get("finding")), "finding_source": c.get("finding_source"),
                        "evidence_ids": list(c.get("evidence_ids") or []), "reason": c.get("reason") or ""}
                       for c in ex.get("claims") or []],
        },
        "who": [{"action": r.get("action"), "actor_id": r.get("actor_id"), "actor_role": r.get("actor_role"),
                 "actor_name": r.get("actor_name"), "at": r.get("created_at"), "reason_code": r.get("reason_code"),
                 "reason_text": r.get("reason_text"), "stage": r.get("stage")}
                for r in reviews if r.get("action") in DECISIVE_ACTIONS],
        "authorized_name": (last_pkg or {}).get("dfAuthorizedName"),
        "when": {"received": case.get("date_received"), "internal_target": case.get("internal_target_date"),
                 "due": case.get("response_due_date"), "decided_at": decided_at,
                 "calendar_days_before_due": days_before_due,
                 "on_time": None if days_before_due is None else days_before_due >= 0,
                 "clock_state": case.get("clock_state")},
        "trust": {"hash_chain": (ex.get("hash_chain") or {}).get("status"),
                  "hash_chain_ok": (ex.get("hash_chain") or {}).get("ok"),
                  "events": (ex.get("hash_chain") or {}).get("events"),
                  "packages": [{"version": c["version"], "ok": c["ok"], "event_id": c.get("event_id")}
                               for c in pkg_checks],
                  "anchor": ex.get("anchor"),
                  "unverified_tables": unverified, "synthetic": ex.get("synthetic"),
                  "model_ids": list((ex.get("versions") or {}).get("model_ids") or [])},
    }
