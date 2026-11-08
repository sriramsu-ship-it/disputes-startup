"""Client-portal read model (CLIENT_VIEWER, own tenant only, read-only). OWNER: web agent.

Every query filters by the viewer's own tenant_id; the caller never passes a tenant from the URL.
Account numbers are shown as last 4 only (R-27).
"""
from __future__ import annotations

from disputes.web.pii import mask_account
from disputes.web.views import COMPLETED_STATES, OPEN_STATES


def dashboard(conn, *, tenant_id: str) -> dict:
    by_state = {r["state"]: r["n"] for r in conn.execute(
        "SELECT state, count(*) AS n FROM cases WHERE tenant_id = %s GROUP BY state", (tenant_id,)).fetchall()}
    by_outcome = {r["o"]: r["n"] for r in conn.execute(
        "SELECT final_outcome AS o, count(*) AS n FROM cases WHERE tenant_id = %s AND final_outcome IS NOT NULL "
        "AND state = ANY(%s) GROUP BY final_outcome", (tenant_id, COMPLETED_STATES)).fetchall()}
    sla = {r["clock_state"] or "UNKNOWN": r["n"] for r in conn.execute(
        "SELECT clock_state, count(*) AS n FROM cases WHERE tenant_id = %s AND state = ANY(%s) GROUP BY clock_state",
        (tenant_id, OPEN_STATES)).fetchall()}
    total = sum(by_state.values())
    return {"total": total, "open": sum(by_state.get(s, 0) for s in OPEN_STATES),
            "completed": sum(by_state.get(s, 0) for s in COMPLETED_STATES),
            "by_state": by_state, "by_outcome": by_outcome,
            "sla": {"ON_TRACK": sla.get("ON_TRACK", 0), "AT_RISK": sla.get("AT_RISK", 0),
                    "BREACHED": sla.get("BREACHED", 0)}}


def case_list(conn, *, tenant_id: str, limit: int = 500) -> list[dict]:
    rows = conn.execute(
        "SELECT case_id, control_number, cra, account_number, date_received, internal_target_date, "
        "response_due_date, clock_state, state, final_outcome FROM cases WHERE tenant_id = %s "
        "ORDER BY (state = ANY(%s)) DESC, response_due_date ASC NULLS LAST, case_id LIMIT %s",
        (tenant_id, OPEN_STATES, limit)).fetchall()
    out = []
    for r in rows:
        r = dict(r)
        r["account"] = mask_account(r.pop("account_number"))
        r["completed"] = r["state"] in COMPLETED_STATES
        out.append(r)
    return out


def case_summary(conn, *, tenant_id: str, case_id: str) -> dict | None:
    r = conn.execute(
        "SELECT case_id, control_number, cra, account_number, date_received, internal_target_date, "
        "response_due_date, clock_state, state, final_outcome FROM cases WHERE tenant_id = %s AND case_id = %s",
        (tenant_id, case_id)).fetchone()
    if r is None:
        return None
    r = dict(r)
    r["account"] = mask_account(r.pop("account_number"))
    r["completed"] = r["state"] in COMPLETED_STATES
    return r
