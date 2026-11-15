"""Client-portal read model (CLIENT_VIEWER, own tenant only, read-only). OWNER: web agent.

Every query filters by the viewer's own tenant_id; the caller never passes a tenant from the URL.
Account numbers are shown as last 4 only (R-27).

Definition (hardening, STATUS known issue 1; PRD R-40 / R-41): a dispute is **completed** when it is
closed: a response package was written (SUBMITTED_STUB, "responded") or it was closed out of scope
(OUT_OF_SCOPE). These are exactly the cases whose audit export R-41 lets the client download. Every
completed case has exactly one outcome in the outcomes panel: its final outcome, or "Out of scope"
for a case closed out of scope by the pipeline (which sets no final_outcome). So the outcomes panel
always sums to the "completed" tile (tested).
"""
from __future__ import annotations

from disputes.web.pii import mask_account
from disputes.web.views import COMPLETED_STATES, OPEN_STATES


# Client-facing status (PRD v1.3 §6.1 Q11): a headline, plus one plain-English line under "In review".
# The audit export keeps the internal states unchanged. Open handoffs ("Needs your action", R-42)
# are not built yet.
CLIENT_HEADLINE = {
    "RECEIVED": "Received", "CLASSIFIED": "Received", "INVESTIGATING": "Received",
    "DRAFT_READY": "In review", "IN_REVIEW": "In review", "ESCALATED": "In review",
    "AWAITING_SECOND_APPROVAL": "In review", "APPROVED": "In review",
    "SUBMITTED_STUB": "Response ready (not sent)", "OUT_OF_SCOPE": "Out of scope: returned to you",
}
CLIENT_HEADLINE_ORDER = ("Received", "In review", "Response ready (not sent)", "Out of scope: returned to you")
_STEP = {"DRAFT_READY": "Waiting for an analyst", "IN_REVIEW": "Analyst review",
         "AWAITING_SECOND_APPROVAL": "Waiting for a second supervisor approval",
         "APPROVED": "Approved; response being prepared"}
_REASON_TEXT = {
    "INTAKE_INVALID": "the request is incomplete", "DOC_UNREADABLE": "a document could not be read",
    "BREACHED": "past the bureau due date", "CLASS_CONFLICT": "the dispute type is unclear",
    "ID_FRAUD_SUSPECTED": "possible identity fraud", "MULTI_ISSUE": "more than one issue disputed",
    "MONTHS_UNDETERMINED": "disputed months unclear", "EVIDENCE_MISSING": "records missing",
    "EVIDENCE_CONFLICT": "evidence conflict", "CLAIM_UNRESOLVED": "a consumer claim needs review",
    "QUOTE_UNLOCATED": "a consumer claim needs review", "UNADDRESSED_CLAIM": "a consumer claim needs review",
    "DRAFT_INVALID": "the draft response needs rewriting", "LLM_UNAVAILABLE": "automatic drafting unavailable",
    "SYSTEM_ERROR": "a processing error (no outcome proposed)",
}


def client_status(state: str, escalation_reasons=()) -> tuple[str, str | None]:
    """(headline, detail) for the client portal."""
    head = CLIENT_HEADLINE.get(state, "In review")
    if state == "ESCALATED":
        why = []
        for r in escalation_reasons or ():
            t = _REASON_TEXT.get(r, "needs a supervisor's review")
            if t not in why:
                why.append(t)
        return head, "Escalated to a supervisor" + (": " + ", ".join(why) if why else "")
    return head, _STEP.get(state)


# The outcome shown for a completed case (see the module docstring).
OUTCOME_SQL = ("COALESCE(final_outcome, CASE WHEN state = 'OUT_OF_SCOPE' THEN 'OUT_OF_SCOPE' END, "
               "'UNKNOWN')")
COMPLETED_DEFINITION = ("Completed = closed: we sent the response (submitted) or closed the dispute as out of "
                        "scope. Each completed dispute is counted once under its outcome.")


def dashboard(conn, *, tenant_id: str) -> dict:
    by_state = {r["state"]: r["n"] for r in conn.execute(
        "SELECT state, count(*) AS n FROM cases WHERE tenant_id = %s GROUP BY state", (tenant_id,)).fetchall()}
    by_outcome = {r["o"]: r["n"] for r in conn.execute(
        f"SELECT {OUTCOME_SQL} AS o, count(*) AS n FROM cases WHERE tenant_id = %s "
        "AND state = ANY(%s) GROUP BY 1", (tenant_id, COMPLETED_STATES)).fetchall()}
    sla = {r["clock_state"] or "UNKNOWN": r["n"] for r in conn.execute(
        "SELECT clock_state, count(*) AS n FROM cases WHERE tenant_id = %s AND state = ANY(%s) GROUP BY clock_state",
        (tenant_id, OPEN_STATES)).fetchall()}
    total = sum(by_state.values())
    by_status: dict[str, int] = {}
    for st_, n in by_state.items():
        h = CLIENT_HEADLINE.get(st_, "In review")
        by_status[h] = by_status.get(h, 0) + n
    return {"total": total, "open": sum(by_state.get(s, 0) for s in OPEN_STATES),
            "by_status": [(h, by_status[h]) for h in CLIENT_HEADLINE_ORDER if h in by_status],
            "completed_definition": COMPLETED_DEFINITION,
            "completed": sum(by_state.get(s, 0) for s in COMPLETED_STATES),
            "by_state": by_state, "by_outcome": by_outcome,
            "sla": {"ON_TRACK": sla.get("ON_TRACK", 0), "AT_RISK": sla.get("AT_RISK", 0),
                    "BREACHED": sla.get("BREACHED", 0)}}


def case_list(conn, *, tenant_id: str, limit: int = 500) -> list[dict]:
    rows = conn.execute(
        "SELECT case_id, control_number, cra, account_number, date_received, internal_target_date, "
        f"response_due_date, clock_state, state, final_outcome, escalation_reasons, {OUTCOME_SQL} AS shown_outcome "
        "FROM cases WHERE tenant_id = %s ORDER BY (state = ANY(%s)) DESC, response_due_date ASC NULLS LAST, case_id LIMIT %s",
        (tenant_id, OPEN_STATES, limit)).fetchall()
    out = []
    for r in rows:
        r = dict(r)
        r["account"] = mask_account(r.pop("account_number"))
        r["completed"] = r["state"] in COMPLETED_STATES
        r["outcome"] = r.pop("shown_outcome") if r["completed"] else None
        r["status"], r["status_detail"] = client_status(r["state"], r.pop("escalation_reasons"))
        out.append(r)
    return out


def case_summary(conn, *, tenant_id: str, case_id: str) -> dict | None:
    r = conn.execute(
        "SELECT case_id, control_number, cra, account_number, date_received, internal_target_date, "
        f"response_due_date, clock_state, state, final_outcome, escalation_reasons, {OUTCOME_SQL} AS shown_outcome "
        "FROM cases WHERE tenant_id = %s AND case_id = %s",
        (tenant_id, case_id)).fetchone()
    if r is None:
        return None
    r = dict(r)
    r["account"] = mask_account(r.pop("account_number"))
    r["completed"] = r["state"] in COMPLETED_STATES
    r["outcome"] = r.pop("shown_outcome") if r["completed"] else None
    r["status"], r["status_detail"] = client_status(r["state"], r.pop("escalation_reasons"))
    return r


def client_timeline(entries: list[dict]) -> list[dict]:
    """The views.timeline(client_view=True) entries mapped to client headlines; moves that do not
    change the headline are dropped."""
    out = []
    for e in entries:
        frm, to = CLIENT_HEADLINE.get(e.get("from") or "", None), CLIENT_HEADLINE.get(e.get("to") or "", "In review")
        if frm == to:
            continue
        out.append({**e, "from_status": frm, "to_status": to})
    return out
