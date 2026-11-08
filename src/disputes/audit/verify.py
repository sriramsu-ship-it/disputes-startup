"""Audit chain verification (ADR-003 §5, R-21, R-32). OWNER: platform-core.

Recomputes every hash from the STORED columns:
    payload_sha256 = sha256(canonical(stored jsonb payload))
    body           = chain.event_body(... occurred_at=rfc3339(stored occurred_at) ...)
    case_hash      = sha256(case_prev_hash + body)     (per (tenant_id, case_id) chain)
    global_hash    = sha256(global_prev_hash + body)   (one chain over all events)
and checks every stored prev pointer against the previous event's stored hash. The first event
that fails any check is reported as `first_broken_event_id`.

What this detects: an edited, inserted or deleted row (chain break); a whole chain rewritten
consistently by a superuser (mismatch with the latest external anchor, audit/anchor.py); the
insert-only triggers being dropped or disabled (`trigger_present`).
What it does not detect: a rewrite of events newer than the latest anchor (anchor every
cfg.anchor_interval_min minutes bounds that window).

Public API (the web module calls these; names and return shapes are fixed):
    verify_case(conn, *, tenant_id, case_id) -> {"ok", "events", "first_broken_event_id", "detail"}
    verify_all(conn, *, anchor_dir=None)    -> {"ok", "events", "first_broken_event_id",
                                                "trigger_present", "anchor": {...}, "detail"}
"""
from __future__ import annotations

from disputes.audit.chain import GENESIS, canonical, event_body, rfc3339, sha256_hex

INSERT_ONLY_TRIGGERS: dict[str, tuple[str, ...]] = {
    "audit_events": ("audit_events_insert_only", "audit_events_no_truncate"),
    "case_artifacts": ("case_artifacts_insert_only", "case_artifacts_no_truncate"),
}

_COLS = ("event_id, tenant_id, case_id, event_type, actor_type, actor_id, actor_role, occurred_at, payload, "
         "payload_sha256, case_prev_hash, case_hash, global_prev_hash, global_hash, schema_version")


def _body(r: dict) -> str:
    return event_body(tenant_id=r["tenant_id"], case_id=r["case_id"], event_type=r["event_type"],
                      actor_type=r["actor_type"], actor_id=r["actor_id"], actor_role=r["actor_role"],
                      occurred_at=rfc3339(r["occurred_at"]), payload_sha256=r["payload_sha256"],
                      schema_version=r["schema_version"])


def _payload_problem(r: dict) -> str | None:
    if sha256_hex(canonical(r["payload"])) != r["payload_sha256"]:
        return f"event {r['event_id']}: payload does not match payload_sha256"
    return None


def _case_problem(r: dict, prev: str, body: str) -> str | None:
    if r["case_prev_hash"] != prev:
        return f"event {r['event_id']}: case_prev_hash does not link to the previous event of case {r['case_id']}"
    if r["case_hash"] != sha256_hex(prev + body):
        return f"event {r['event_id']}: case_hash does not match recomputed hash"
    return None


def verify_case(conn, *, tenant_id: str, case_id: str) -> dict:
    """Recompute one case's chain. A case with no events is reported ok with events=0."""
    rows = conn.execute(f"SELECT {_COLS} FROM audit_events WHERE tenant_id = %s AND case_id = %s "
                        "ORDER BY event_id", (tenant_id, case_id)).fetchall()
    prev = GENESIS
    for r in rows:
        problem = _payload_problem(r) or _case_problem(r, prev, _body(r))
        if problem:
            return {"ok": False, "events": len(rows), "first_broken_event_id": r["event_id"], "detail": problem}
        prev = r["case_hash"]
    return {"ok": True, "events": len(rows), "first_broken_event_id": None,
            "detail": f"case chain intact ({len(rows)} events)"}


def triggers_present(conn) -> bool:
    """True when every insert-only trigger exists and is enabled (pg_trigger.tgenabled != 'D')."""
    rows = conn.execute(
        "SELECT c.relname AS tbl, t.tgname AS name, t.tgenabled AS enabled FROM pg_trigger t "
        "JOIN pg_class c ON c.oid = t.tgrelid WHERE NOT t.tgisinternal AND c.relname = ANY(%s)",
        (list(INSERT_ONLY_TRIGGERS),)).fetchall()
    have = {(r["tbl"], r["name"]) for r in rows if r["enabled"] != "D"}
    return all((tbl, name) in have for tbl, names in INSERT_ONLY_TRIGGERS.items() for name in names)


def _check_anchor(conn, anchor_dir: str | None) -> dict:
    if anchor_dir is None:
        return {"checked": False, "ok": None, "detail": "no anchor directory given"}
    from disputes.audit.anchor import latest_anchor
    try:
        a = latest_anchor(anchor_dir)
    except Exception as e:  # unreadable anchor store is a verification failure, not a crash
        return {"checked": True, "ok": False, "detail": f"anchor store unreadable: {type(e).__name__}: {e}"}
    if a is None:
        return {"checked": False, "ok": None, "detail": f"no anchor found in {anchor_dir}"}
    head_id, want = int(a["global_head_event_id"]), a["global_hash"]
    if head_id == 0:
        ok = want == GENESIS
        return {"checked": True, "ok": ok, "detail": "anchor of an empty log" + ("" if ok else " has a bad hash")}
    row = conn.execute("SELECT global_hash FROM audit_events WHERE event_id = %s", (head_id,)).fetchone()
    if row is None:
        return {"checked": True, "ok": False,
                "detail": f"anchored event {head_id} is missing from the database (truncation or rewrite)"}
    if row["global_hash"] != want:
        return {"checked": True, "ok": False,
                "detail": f"global hash at anchored event {head_id} does not match the anchor written at "
                          f"{a.get('at')} (chain rewritten)"}
    return {"checked": True, "ok": True, "detail": f"matches anchor at event {head_id} ({a.get('at')})"}


def verify_all(conn, *, anchor_dir: str | None = None) -> dict:
    """Recompute the global chain and every per-case chain, check the insert-only triggers and
    compare with the latest anchor (if `anchor_dir` is given and holds one)."""
    rows = conn.execute(f"SELECT {_COLS} FROM audit_events ORDER BY event_id").fetchall()
    gprev = GENESIS
    case_heads: dict[tuple[str, str], str] = {}
    first_broken = None
    problem = None
    for r in rows:
        body = _body(r)
        problem = _payload_problem(r)
        if problem is None and r["global_prev_hash"] != gprev:
            problem = f"event {r['event_id']}: global_prev_hash does not link to the previous event"
        if problem is None and r["global_hash"] != sha256_hex(gprev + body):
            problem = f"event {r['event_id']}: global_hash does not match recomputed hash"
        if problem is None:
            if r["case_id"] is None:
                if r["case_prev_hash"] is not None or r["case_hash"] is not None:
                    problem = f"event {r['event_id']}: case-less event carries case hashes"
            else:
                key = (r["tenant_id"], r["case_id"])
                problem = _case_problem(r, case_heads.get(key, GENESIS), body)
                if problem is None:
                    case_heads[key] = r["case_hash"]
        if problem:
            first_broken = r["event_id"]
            break
        gprev = r["global_hash"]
    trig = triggers_present(conn)
    anchor = _check_anchor(conn, anchor_dir)
    chains_ok = first_broken is None
    ok = chains_ok and trig and anchor["ok"] is not False
    parts = [problem if problem else f"global and {len(case_heads)} case chains intact ({len(rows)} events)"]
    if not trig:
        parts.append("insert-only triggers missing or disabled")
    parts.append(f"anchor: {anchor['detail']}")
    return {"ok": ok, "events": len(rows), "first_broken_event_id": first_broken, "trigger_present": trig,
            "anchor": anchor, "detail": "; ".join(parts)}
