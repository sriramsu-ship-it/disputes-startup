"""Tenant-scoped repository for cases, artifacts and attachments.

Every function takes `tenant_id` and every statement filters or inserts by it (ADR-008).
State changes go through `workflow.state_machine.transition`, which calls `set_state` here
and writes the audit event in the same transaction. Artifacts are insert-only and versioned.
"""
from __future__ import annotations

from typing import Any

import psycopg

from disputes.audit.chain import canonical, sha256_hex
from disputes.domain import ArtifactKind, to_jsonable


class NotFound(LookupError):
    pass


class StaleVersion(RuntimeError):
    """Optimistic-concurrency conflict: the case changed since it was read."""


CASE_COLUMNS = (
    "case_id", "tenant_id", "channel", "control_number", "cra", "account_number", "account_last4",
    "date_received", "response_due_date", "internal_target_date", "clock_state", "state",
    "categories", "escalation_reasons", "proposed_outcome", "final_outcome", "suspicion_level",
    "priority", "repeat_of_case_id", "assigned_to", "raw_payload_sha256", "synthetic", "version",
    "created_at", "updated_at",
)
_UPDATABLE = {"clock_state", "categories", "escalation_reasons", "proposed_outcome", "final_outcome",
              "suspicion_level", "priority", "repeat_of_case_id", "assigned_to", "internal_target_date",
              "response_due_date", "date_received"}


def insert_case(conn: psycopg.Connection, *, tenant_id: str, case: dict) -> dict:
    cols = {k: v for k, v in case.items() if k in CASE_COLUMNS and k != "tenant_id"}
    cols["tenant_id"] = tenant_id
    names = ", ".join(cols)
    marks = ", ".join(["%s"] * len(cols))
    return conn.execute(f"INSERT INTO cases ({names}) VALUES ({marks}) RETURNING *",
                        tuple(cols.values())).fetchone()


def get_case(conn: psycopg.Connection, *, tenant_id: str, case_id: str, for_update: bool = False) -> dict:
    sql = "SELECT * FROM cases WHERE tenant_id = %s AND case_id = %s" + (" FOR UPDATE" if for_update else "")
    row = conn.execute(sql, (tenant_id, case_id)).fetchone()
    if row is None:
        raise NotFound(case_id)
    return row


def find_case_by_control_number(conn, *, tenant_id: str, control_number: str) -> dict | None:
    return conn.execute("SELECT * FROM cases WHERE tenant_id = %s AND control_number = %s",
                        (tenant_id, control_number)).fetchone()


def prior_cases_for_account(conn, *, tenant_id: str, account_number: str) -> list[dict]:
    """For R-04 repeat detection: earlier cases on the same account, newest first."""
    return conn.execute(
        "SELECT case_id, categories, date_received, state, proposed_outcome, final_outcome "
        "FROM cases WHERE tenant_id = %s AND account_number = %s ORDER BY date_received DESC NULLS LAST",
        (tenant_id, account_number)).fetchall()


def list_cases(conn, *, tenant_id: str, states: list[str] | None = None,
               flag: str | None = None, limit: int = 500) -> list[dict]:
    """R-16 queue order: ID fraud (priority) first, then AT_RISK/BREACHED, then internal target date."""
    where, params = ["tenant_id = %s"], [tenant_id]
    if states:
        where.append("state = ANY(%s)")
        params.append(states)
    if flag:
        where.append("%s = ANY(escalation_reasons)")
        params.append(flag)
    params.append(limit)
    return conn.execute(
        f"SELECT * FROM cases WHERE {' AND '.join(where)} "
        "ORDER BY priority DESC, (clock_state IN ('AT_RISK','BREACHED')) DESC, "
        "internal_target_date ASC NULLS LAST, created_at ASC LIMIT %s", params).fetchall()


def update_case_fields(conn, *, tenant_id: str, case_id: str, expected_version: int | None = None,
                       **fields: Any) -> dict:
    bad = set(fields) - _UPDATABLE
    if bad:
        raise ValueError(f"not updatable here: {sorted(bad)} (state changes go through the state machine)")
    return _update(conn, tenant_id, case_id, expected_version, fields)


def set_state(conn, *, tenant_id: str, case_id: str, state: str, expected_version: int | None = None) -> dict:
    """Low-level; call workflow.state_machine.transition instead (it validates and audits)."""
    return _update(conn, tenant_id, case_id, expected_version, {"state": state})


def _update(conn, tenant_id, case_id, expected_version, fields: dict) -> dict:
    if not fields:
        return get_case(conn, tenant_id=tenant_id, case_id=case_id)
    sets = ", ".join(f"{k} = %s" for k in fields) + ", version = version + 1, updated_at = now()"
    params = list(fields.values()) + [tenant_id, case_id]
    sql = f"UPDATE cases SET {sets} WHERE tenant_id = %s AND case_id = %s"
    if expected_version is not None:
        sql += " AND version = %s"
        params.append(expected_version)
    row = conn.execute(sql + " RETURNING *", params).fetchone()
    if row is None:
        if expected_version is not None:
            raise StaleVersion(case_id)
        raise NotFound(case_id)
    return row


# ---------------------------------------------------------------- artifacts (insert-only)
def put_artifact(conn, *, tenant_id: str, case_id: str, kind: ArtifactKind | str, data: Any,
                 created_by: str) -> dict:
    """Store a new version of an artifact. Never updates an existing version."""
    payload = to_jsonable(data)
    js = canonical(payload)
    nxt = conn.execute(
        "SELECT COALESCE(MAX(version), 0) + 1 AS v FROM case_artifacts "
        "WHERE tenant_id = %s AND case_id = %s AND kind = %s", (tenant_id, case_id, str(kind))).fetchone()["v"]
    return conn.execute(
        "INSERT INTO case_artifacts (tenant_id, case_id, kind, version, data, data_sha256, created_by) "
        "VALUES (%s,%s,%s,%s,%s::jsonb,%s,%s) RETURNING id, version, data_sha256",
        (tenant_id, case_id, str(kind), nxt, js, sha256_hex(js), created_by)).fetchone()


def latest_artifact(conn, *, tenant_id: str, case_id: str, kind: ArtifactKind | str) -> dict | None:
    """The newest version's row (keys: version, data, data_sha256, created_by, created_at) or None."""
    return conn.execute(
        "SELECT version, data, data_sha256, created_by, created_at FROM case_artifacts "
        "WHERE tenant_id = %s AND case_id = %s AND kind = %s ORDER BY version DESC LIMIT 1",
        (tenant_id, case_id, str(kind))).fetchone()


def artifact_history(conn, *, tenant_id: str, case_id: str, kind: ArtifactKind | str | None = None) -> list[dict]:
    if kind is None:
        return conn.execute(
            "SELECT kind, version, data, data_sha256, created_by, created_at FROM case_artifacts "
            "WHERE tenant_id = %s AND case_id = %s ORDER BY id", (tenant_id, case_id)).fetchall()
    return conn.execute(
        "SELECT kind, version, data, data_sha256, created_by, created_at FROM case_artifacts "
        "WHERE tenant_id = %s AND case_id = %s AND kind = %s ORDER BY version",
        (tenant_id, case_id, str(kind))).fetchall()


# ---------------------------------------------------------------- attachments
def insert_attachment(conn, *, tenant_id: str, case_id: str, att: dict) -> None:
    conn.execute(
        "INSERT INTO attachments (tenant_id, case_id, attachment_id, file_name, media_type, page_count, "
        "sha256, extracted_text, metadata) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s::jsonb)",
        (tenant_id, case_id, att["attachment_id"], att["file_name"], att["media_type"], att["page_count"],
         att["sha256"], att["extracted_text"], canonical(att.get("metadata") or {})))


def list_attachments(conn, *, tenant_id: str, case_id: str) -> list[dict]:
    return conn.execute("SELECT * FROM attachments WHERE tenant_id = %s AND case_id = %s ORDER BY attachment_id",
                        (tenant_id, case_id)).fetchall()


def record_duplicate(conn, *, tenant_id: str, control_number: str, original_case_id: str,
                     raw_payload_sha256: str) -> None:
    conn.execute("INSERT INTO duplicate_intakes (tenant_id, control_number, original_case_id, raw_payload_sha256) "
                 "VALUES (%s,%s,%s,%s)", (tenant_id, control_number, original_case_id, raw_payload_sha256))


def audit_events_for_case(conn, *, tenant_id: str, case_id: str) -> list[dict]:
    return conn.execute("SELECT * FROM audit_events WHERE tenant_id = %s AND case_id = %s ORDER BY event_id",
                        (tenant_id, case_id)).fetchall()


# ---------------------------------------------------------------- case IDs (platform-core, migration 0003)
def _prefix_candidate(tenant_id: str) -> str:
    """'synthetic-tenant-0' -> 'ST0'; 'ops' -> 'OPS'. Letters: initials; digit groups kept whole."""
    import re
    parts = [p for p in re.split(r"[^A-Za-z0-9]+", tenant_id) if p]
    if len(parts) <= 1:
        cand = re.sub(r"[^A-Za-z0-9]", "", tenant_id).upper()[:4]
    else:
        cand = "".join(p if p.isdigit() else p[0] for p in parts).upper()
    cand = cand[:10]
    return cand if len(cand) >= 2 else (cand + "X")[:2] if cand else "TN"


def tenant_case_prefix(conn, *, tenant_id: str) -> str:
    """The tenant's case-ID prefix, allocated on first use and unique across tenants."""
    row = conn.execute("SELECT prefix FROM tenant_case_prefixes WHERE tenant_id = %s", (tenant_id,)).fetchone()
    if row:
        return row["prefix"]
    base = _prefix_candidate(tenant_id)
    for n in range(0, 1000):
        cand = base if n == 0 else f"{base}{n + 1}"
        row = conn.execute(
            "INSERT INTO tenant_case_prefixes (tenant_id, prefix) SELECT %s, %s "
            "WHERE NOT EXISTS (SELECT 1 FROM tenant_case_prefixes WHERE prefix = %s) "
            "ON CONFLICT (tenant_id) DO NOTHING RETURNING prefix", (tenant_id, cand, cand)).fetchone()
        if row:
            return row["prefix"]
        again = conn.execute("SELECT prefix FROM tenant_case_prefixes WHERE tenant_id = %s",
                             (tenant_id,)).fetchone()
        if again:                       # another transaction allocated it for this tenant
            return again["prefix"]
    raise RuntimeError(f"could not allocate a case prefix for tenant {tenant_id}")


def next_case_id(conn, *, tenant_id: str, day) -> str:
    """`<PREFIX>-<yyyymmdd>-<seq:05d>`; the per-tenant, per-day counter is incremented atomically."""
    prefix = tenant_case_prefix(conn, tenant_id=tenant_id)
    seq = conn.execute(
        "INSERT INTO case_id_counters (tenant_id, day, last_seq) VALUES (%s, %s, 1) "
        "ON CONFLICT (tenant_id, day) DO UPDATE SET last_seq = case_id_counters.last_seq + 1 "
        "RETURNING last_seq", (tenant_id, day)).fetchone()["last_seq"]
    return f"{prefix}-{day.strftime('%Y%m%d')}-{seq:05d}"


def find_case_for_job(conn, *, tenant_id: str, case_id: str | None, control_number: str | None) -> dict | None:
    """Locate the case a job worked on (by case_id, else by control number), tenant-scoped."""
    if case_id:
        return conn.execute("SELECT * FROM cases WHERE tenant_id = %s AND case_id = %s",
                            (tenant_id, case_id)).fetchone()
    if control_number:
        return conn.execute("SELECT * FROM cases WHERE tenant_id = %s AND control_number = %s",
                            (tenant_id, control_number)).fetchone()
    return None
