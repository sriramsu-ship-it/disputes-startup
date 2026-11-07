"""Append-only, hash-chained audit events (ADR-003, R-21).

`append_event` is the ONLY way any module writes to `audit_events`. It must be called
inside the same transaction as the change it records, so a state change can never
commit without its audit record.

Hash definition (ADR-003 §2), shared with `verify` (audit/verify.py):
    body       = canonical JSON of {tenant_id, case_id, event_type, actor_type, actor_id,
                                    actor_role, occurred_at, payload_sha256, schema_version}
    case_hash   = sha256(case_prev_hash + body)     (per-case chain; NULL for case-less events)
    global_hash = sha256(global_prev_hash + body)   (one chain over all events)
Genesis prev hash = 64 zeros. occurred_at is RFC 3339 UTC with microseconds, from the DB clock.
"""
from __future__ import annotations

import hashlib
import json
from datetime import timezone

import psycopg

from disputes.domain import ActorType, to_jsonable

GENESIS = "0" * 64
GLOBAL_LOCK_KEY = 7_743_001          # pg_advisory_xact_lock key serialising chain writes
SCHEMA_VERSION = 1


def canonical(obj) -> str:
    return json.dumps(to_jsonable(obj), sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def sha256_hex(s: str | bytes) -> str:
    return hashlib.sha256(s.encode("utf-8") if isinstance(s, str) else s).hexdigest()


def rfc3339(ts) -> str:
    return ts.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def event_body(*, tenant_id, case_id, event_type, actor_type, actor_id, actor_role,
               occurred_at: str, payload_sha256: str, schema_version: int = SCHEMA_VERSION) -> str:
    return canonical({
        "tenant_id": tenant_id, "case_id": case_id, "event_type": event_type,
        "actor_type": str(actor_type), "actor_id": actor_id, "actor_role": actor_role,
        "occurred_at": occurred_at, "payload_sha256": payload_sha256,
        "schema_version": schema_version,
    })


def append_event(conn: psycopg.Connection, *, tenant_id: str, case_id: str | None,
                 event_type: str, actor_type: ActorType | str, actor_id: str,
                 actor_role: str | None, payload: dict) -> dict:
    """Insert one audit event, extending the case chain and the global chain.

    Must run inside an open transaction (`with conn.transaction():`). Takes a global
    transaction-scoped advisory lock so chain heads are read and written serially.
    Returns the inserted row (event_id, case_hash, global_hash, occurred_at).
    """
    if not conn.info.transaction_status:  # IDLE means no open transaction
        raise RuntimeError("append_event must be called inside a transaction")
    conn.execute("SELECT pg_advisory_xact_lock(%s)", (GLOBAL_LOCK_KEY,))
    now = conn.execute("SELECT clock_timestamp() AS t").fetchone()["t"]
    occurred = rfc3339(now)
    payload_json = canonical(payload)
    payload_hash = sha256_hex(payload_json)
    body = event_body(tenant_id=tenant_id, case_id=case_id, event_type=event_type,
                      actor_type=actor_type, actor_id=actor_id, actor_role=actor_role,
                      occurred_at=occurred, payload_sha256=payload_hash)

    g = conn.execute("SELECT global_hash FROM audit_events ORDER BY event_id DESC LIMIT 1").fetchone()
    global_prev = g["global_hash"] if g else GENESIS
    case_prev = case_hash = None
    if case_id is not None:
        c = conn.execute("SELECT case_hash FROM audit_events WHERE case_id = %s AND tenant_id = %s "
                         "ORDER BY event_id DESC LIMIT 1", (case_id, tenant_id)).fetchone()
        case_prev = c["case_hash"] if c else GENESIS
        case_hash = sha256_hex(case_prev + body)
    global_hash = sha256_hex(global_prev + body)

    row = conn.execute(
        "INSERT INTO audit_events (tenant_id, case_id, event_type, actor_type, actor_id, actor_role, "
        "occurred_at, payload, payload_sha256, case_prev_hash, case_hash, global_prev_hash, global_hash, "
        "schema_version) VALUES (%s,%s,%s,%s,%s,%s,%s,%s::jsonb,%s,%s,%s,%s,%s,%s) "
        "RETURNING event_id, case_hash, global_hash, occurred_at",
        (tenant_id, case_id, event_type, str(actor_type), actor_id, actor_role, now, payload_json,
         payload_hash, case_prev, case_hash, global_prev, global_hash, SCHEMA_VERSION)).fetchone()
    return row
