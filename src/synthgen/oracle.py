"""Gold-label oracle for SYNTHETIC fixtures (generator intent, T1-style labels).

Derives the gold route/outcome from the generated data using the PRD v1.1 rules
(R-02, R-03, R-05, R-06/R-07, R-08, R-09, R-10). The generator cross-checks this
against each scenario's declared intent and refuses to emit a case if they differ.

CIRCULARITY WARNING (REV §2 R-26, U20, U31): these labels encode the same rules
the product will implement. They are fine for generator-labelled safety sets
(T1, spot-checked by Sriram per B8) but must NEVER be used as T3 gold, and the
Stage 1 R-10 implementation must be written independently: production code under
src/disputes_core must not import synthgen.oracle (enforced by a test).
"""
from __future__ import annotations

import re
from datetime import date

from . import bizdays, tables

REQUIRED_ACDV_FIELDS = (
    "control_number", "cra", "date_received", "response_due_date",
    "account_number", "consumer", "dispute_codes", "free_text", "attachments",
)
ISO_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
UNREADABLE_CHARS_PER_PAGE = 200  # R-03 default (config)
CONFLICT_NOTE_TYPES = {"HARDSHIP", "DEFERRAL", "FORBEARANCE"}


def _blank(v) -> bool:
    return v is None or (isinstance(v, str) and not v.strip())


def intake_problems(acdv: dict) -> list[str]:
    """R-01/R-02: missing, empty or unparseable required fields."""
    problems = []
    for f in REQUIRED_ACDV_FIELDS:
        if f not in acdv:
            problems.append(f"missing:{f}")
            continue
        v = acdv[f]
        if f in ("date_received", "response_due_date"):
            if not isinstance(v, str) or not ISO_DATE.match(v):
                problems.append(f"unparseable_date:{f}")
            else:
                try:
                    date.fromisoformat(v)
                except ValueError:
                    problems.append(f"unparseable_date:{f}")
        elif f == "consumer":
            if not isinstance(v, dict) or _blank(v.get("first_name")) or _blank(v.get("last_name")):
                problems.append("empty:consumer_name")
        elif f == "dispute_codes":
            if not isinstance(v, list) or not v or any(_blank(c) for c in v):
                problems.append("empty:dispute_codes")
        elif f == "attachments":
            if not isinstance(v, list):
                problems.append("invalid:attachments")
        elif _blank(v):
            problems.append(f"empty:{f}")
    return problems


def attachment_unreadable(att: dict) -> bool:
    """R-03/R-33: image-only or <200 extracted chars per page, or an archive."""
    if att.get("media_type") in ("application/zip", "application/x-zip-compressed"):
        return True
    pages = max(1, int(att.get("page_count", 1)))
    return len(att.get("extracted_text", "")) / pages < UNREADABLE_CHARS_PER_PAGE


def _month_bounds(m: str) -> tuple[date, date]:
    y, mo = int(m[:4]), int(m[5:7])
    start = date(y, mo, 1)
    end = date(y + (mo == 12), (mo % 12) + 1, 1)
    from datetime import timedelta
    return start, end - timedelta(days=1)


def note_overlaps(note: dict, month: str) -> bool:
    s, e = _month_bounds(month)
    return date.fromisoformat(note["start_date"]) <= e and date.fromisoformat(note["end_date"]) >= s


def derive_gold(envelope: dict, sor_account: dict | None, intent: dict, seen_control_numbers: set) -> dict:
    """Return gold {route, outcome, escalation_reasons, month_results, corrections, disputed_months}."""
    acdv = envelope["acdv"]
    ingest = date.fromisoformat(envelope["fixture_meta"]["ingest_date"])
    out = {"outcome": None, "escalation_reasons": [], "month_results": {}, "corrections": [],
           "disputed_months": [], "clock_state_at_intake": None}

    cn = acdv.get("control_number")
    if isinstance(cn, str) and cn.strip() and cn in seen_control_numbers:
        out["outcome"] = "DUPLICATE_IGNORED"
        return out

    reasons: list[str] = []
    probs = intake_problems(acdv)
    if probs:
        out["outcome"] = "ESCALATED"
        out["escalation_reasons"] = ["INTAKE_INVALID"]
        out["intake_problems"] = probs
        return out

    due = date.fromisoformat(acdv["response_due_date"])
    out["clock_state_at_intake"] = bizdays.clock_state(ingest, due)
    if out["clock_state_at_intake"] == "BREACHED":
        reasons.append("BREACHED")
    if any(attachment_unreadable(a) for a in acdv["attachments"]):
        reasons.append("DOC_UNREADABLE")

    gold_cats = set(intent["categories"])
    code_cats = set()
    for c in acdv["dispute_codes"]:
        code_cats |= set(tables.categories_for_code(c))

    if "IDENTITY_FRAUD" in gold_cats or "IDENTITY_FRAUD" in code_cats:
        out["outcome"] = "ESCALATED"
        out["escalation_reasons"] = reasons + ["ID_FRAUD_SUSPECTED"]
        return out
    if code_cats != gold_cats:
        reasons.append("CLASS_CONFLICT")
    if len(gold_cats) > 1:
        reasons.append("MULTI_ISSUE")
    if gold_cats != {"PAYMENT_HISTORY"}:
        if reasons:
            out["outcome"] = "ESCALATED"
            out["escalation_reasons"] = reasons
        else:
            out["outcome"] = "OUT_OF_SCOPE"
        return out
    if "CLASS_CONFLICT" in reasons:
        out["outcome"] = "ESCALATED"
        out["escalation_reasons"] = reasons
        return out

    # Investigation (payment history only).
    claims = intent.get("claims", [])
    months = set(acdv.get("disputed_months", []))
    for c in claims:
        months |= set(c.get("months", []))
    months = sorted(months)
    out["disputed_months"] = months
    if not months:
        reasons.append("MONTHS_UNDETERMINED")
        out["outcome"] = "ESCALATED"
        out["escalation_reasons"] = reasons
        return out

    cycles = {c["cycle_month"]: c for c in (sor_account or {}).get("cycles", [])}
    mismatches = []
    for m in months:
        cyc = cycles.get(m)
        if cyc is None:
            out["month_results"][m] = "NO_DATA"
            continue
        expected = tables.rating_for_dpd(cyc["dpd_at_cycle"])
        if expected == cyc["reported_rating"]:
            out["month_results"][m] = "MATCH"
        else:
            out["month_results"][m] = "MISMATCH"
            mismatches.append({"month": m, "reported_rating": cyc["reported_rating"], "corrected_rating": expected})
    if "NO_DATA" in out["month_results"].values():
        reasons.append("EVIDENCE_MISSING")
    notes = (sor_account or {}).get("notes", [])
    if any(n["type"] in CONFLICT_NOTE_TYPES and note_overlaps(n, m) for n in notes for m in months):
        reasons.append("EVIDENCE_CONFLICT")

    if reasons:
        out["outcome"] = "ESCALATED"
        out["escalation_reasons"] = reasons
        return out
    if mismatches:
        out["outcome"] = "MODIFY"
        out["corrections"] = mismatches
        return out
    if all(c["finding"] == "CONTRADICTED" for c in claims):
        out["outcome"] = "VERIFIED_AS_REPORTED"
        return out
    out["outcome"] = "ESCALATED"
    out["escalation_reasons"] = ["CLAIM_UNRESOLVED"]
    return out
