"""R-24 instrumentation and R-21 case-read events. OWNER: web agent.

`case_metrics` rows (operational, 90-day retention R-31): opened | first_viewed | active_seconds |
decided. Active seconds come from the browser (Page Visibility + focus/blur + idle cutoff, see
static/review.js) and are capped server-side per beacon. CSV export is for SUPERVISOR/ADMIN.
"""
from __future__ import annotations

import csv
import io
import json

from disputes.audit.reads import record_case_read as record_core_read
from disputes.domain import Role

MAX_BEACON_SECONDS = 300.0       # one beacon can never claim more than this (client sends every 30 s)
METRIC_NAMES = ("opened", "first_viewed", "active_seconds", "decided")


def record(conn, *, tenant_id: str, case_id: str, user_id: str | None, metric: str, value: float | None = None,
           detail: dict | None = None) -> None:
    if metric not in METRIC_NAMES:
        raise ValueError(metric)
    conn.execute("INSERT INTO case_metrics (tenant_id, case_id, user_id, metric, value, detail) "
                 "VALUES (%s,%s,%s,%s,%s,%s::jsonb)",
                 (tenant_id, case_id, user_id, metric, value, json.dumps(detail or {})))


def record_open(conn, *, tenant_id: str, case_id: str, user_id: str) -> None:
    record(conn, tenant_id=tenant_id, case_id=case_id, user_id=user_id, metric="opened")
    seen = conn.execute("SELECT 1 FROM case_metrics WHERE tenant_id = %s AND case_id = %s "
                        "AND metric = 'first_viewed' LIMIT 1", (tenant_id, case_id)).fetchone()
    if not seen:
        record(conn, tenant_id=tenant_id, case_id=case_id, user_id=user_id, metric="first_viewed")


def record_active_seconds(conn, *, tenant_id: str, case_id: str, user_id: str, seconds: float) -> float:
    s = max(0.0, min(float(seconds), MAX_BEACON_SECONDS))
    if s > 0:
        with conn.transaction():
            record(conn, tenant_id=tenant_id, case_id=case_id, user_id=user_id, metric="active_seconds", value=s)
    return s


def seconds_since_first_view(conn, *, tenant_id: str, case_id: str) -> float | None:
    r = conn.execute("SELECT EXTRACT(EPOCH FROM (now() - MIN(at))) AS s FROM case_metrics "
                     "WHERE tenant_id = %s AND case_id = %s AND metric = 'first_viewed'",
                     (tenant_id, case_id)).fetchone()
    return float(r["s"]) if r and r["s"] is not None else None


def record_case_read(conn, *, tenant_id: str, case_id: str, user_id: str, role: str, surface: str) -> None:
    """R-21: AUDITOR / ADMIN reads are audited (platform-core audit.reads, own transaction)."""
    if role not in (Role.AUDITOR.value, Role.ADMIN.value):
        return
    record_core_read(conn, tenant_id=tenant_id, case_id=case_id, user_id=user_id, role=role,
                     detail={"surface": surface})


CSV_COLUMNS = ("case_id", "state", "opened_count", "first_viewed_at", "active_review_seconds", "decided_at",
               "decision_seconds", "last_action", "override", "reason_code", "escalation_reasons")


def metrics_csv(conn, *, tenant_id: str) -> str:
    rows = conn.execute(
        "SELECT c.case_id, c.state, c.escalation_reasons, "
        " count(*) FILTER (WHERE m.metric = 'opened') AS opened_count, "
        " min(m.at) FILTER (WHERE m.metric = 'first_viewed') AS first_viewed_at, "
        " coalesce(sum(m.value) FILTER (WHERE m.metric = 'active_seconds'), 0) AS active_seconds, "
        " max(m.at) FILTER (WHERE m.metric = 'decided') AS decided_at "
        "FROM cases c LEFT JOIN case_metrics m ON m.case_id = c.case_id AND m.tenant_id = c.tenant_id "
        "WHERE c.tenant_id = %s GROUP BY c.case_id ORDER BY c.case_id", (tenant_id,)).fetchall()
    last = {r["case_id"]: r for r in conn.execute(
        "SELECT DISTINCT ON (case_id) case_id, value, detail FROM case_metrics "
        "WHERE tenant_id = %s AND metric = 'decided' ORDER BY case_id, at DESC, id DESC", (tenant_id,)).fetchall()}
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(CSV_COLUMNS)
    for r in rows:
        d = last.get(r["case_id"])
        det = (d or {}).get("detail") or {}
        w.writerow([r["case_id"], r["state"], r["opened_count"],
                    r["first_viewed_at"].isoformat() if r["first_viewed_at"] else "",
                    round(float(r["active_seconds"]), 1),
                    r["decided_at"].isoformat() if r["decided_at"] else "",
                    round(d["value"], 1) if d and d["value"] is not None else "",
                    det.get("action", ""), "" if not d else ("yes" if det.get("override") else "no"),
                    det.get("reason_code") or "", ";".join(r["escalation_reasons"] or [])])
    return buf.getvalue()
