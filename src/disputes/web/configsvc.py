"""R-21 / R-18 config administration. OWNER: web agent.

Effective config = `Config` defaults overlaid by the newest `config_versions` row per key for the
platform tenant 'ops'. A change is proposed by one ADMIN (`propose_change`) and applied only when a
different ADMIN approves it (`decide_change`); both steps are audited ADMIN events written in the
same transaction. `mode` cannot be changed here (R-35 live-mode gate is a deploy decision) and
`llm_model_id` cannot be changed here (R-30: a model change must pass the full eval first).
"""
from __future__ import annotations

import json
from dataclasses import fields

from disputes.audit.chain import append_event
from disputes.config import Config, defaults
from disputes.domain import ActorType, Role

PLATFORM_TENANT = "ops"
LOCKED_KEYS = frozenset({"mode", "llm_model_id"})
MIN_REASON_CHARS = 10


class ConfigError(ValueError):
    pass


class ConfigForbidden(PermissionError):
    pass


def _types() -> dict[str, type]:
    d = defaults()
    return {f.name: type(getattr(d, f.name)) for f in fields(Config)}


def effective_config(conn, tenant_id: str = PLATFORM_TENANT) -> Config:
    rows = conn.execute(
        "SELECT DISTINCT ON (key) key, value FROM config_versions WHERE tenant_id = %s "
        "ORDER BY key, version DESC", (tenant_id,)).fetchall()
    types = _types()
    over = {r["key"]: types[r["key"]](r["value"]) for r in rows if r["key"] in types}
    return defaults().with_overrides(**over)


def current_rows(conn, tenant_id: str = PLATFORM_TENANT) -> list[dict]:
    """[{key, value, default, type, version, changed_by, changed_at, locked}] for the admin page."""
    cfg = effective_config(conn, tenant_id)
    d = defaults()
    meta = {r["key"]: r for r in conn.execute(
        "SELECT DISTINCT ON (key) key, version, changed_by, changed_at FROM config_versions "
        "WHERE tenant_id = %s ORDER BY key, version DESC", (tenant_id,)).fetchall()}
    out = []
    for f in fields(Config):
        m = meta.get(f.name) or {}
        out.append({"key": f.name, "value": getattr(cfg, f.name), "default": getattr(d, f.name),
                    "type": type(getattr(d, f.name)).__name__, "version": m.get("version"),
                    "changed_by": m.get("changed_by"), "changed_at": m.get("changed_at"),
                    "locked": f.name in LOCKED_KEYS})
    return out


def parse_value(key: str, raw: str):
    types = _types()
    if key not in types:
        raise ConfigError(f"unknown config key {key!r}")
    if key in LOCKED_KEYS:
        raise ConfigError(f"{key} cannot be changed from the admin page")
    t = types[key]
    try:
        v = t(str(raw).strip())
    except ValueError as e:
        raise ConfigError(f"{key} must be a {t.__name__}") from e
    if t in (int, float) and v <= 0:
        raise ConfigError(f"{key} must be greater than zero")
    return v


def _require_admin(actor) -> None:
    if actor.role != Role.ADMIN:
        raise ConfigForbidden("only an ADMIN can change config")


def propose_change(conn, *, actor, key: str, raw_value: str, reason: str,
                   tenant_id: str = PLATFORM_TENANT) -> dict:
    _require_admin(actor)
    value = parse_value(key, raw_value)
    if len((reason or "").strip()) < MIN_REASON_CHARS:
        raise ConfigError(f"reason must be at least {MIN_REASON_CHARS} characters")
    old = getattr(effective_config(conn, tenant_id), key)
    if old == value:
        raise ConfigError(f"{key} is already {value}")
    with conn.transaction():
        row = conn.execute(
            "INSERT INTO config_change_requests (tenant_id, key, old_value, new_value, reason, proposed_by) "
            "VALUES (%s,%s,%s::jsonb,%s::jsonb,%s,%s) RETURNING *",
            (tenant_id, key, json.dumps(old), json.dumps(value), reason.strip(), actor.user_id)).fetchone()
        append_event(conn, tenant_id=tenant_id, case_id=None, event_type="CONFIG_CHANGE_PROPOSED",
                     actor_type=ActorType.HUMAN, actor_id=actor.user_id, actor_role=str(actor.role),
                     payload={"request_id": row["request_id"], "key": key, "old_value": old, "new_value": value,
                              "reason": reason.strip()})
    return row


def pending(conn, tenant_id: str = PLATFORM_TENANT) -> list[dict]:
    return conn.execute("SELECT r.*, u.display_name AS proposer_name FROM config_change_requests r "
                        "JOIN users u ON u.user_id = r.proposed_by "
                        "WHERE r.tenant_id = %s AND r.status = 'PENDING' ORDER BY r.request_id",
                        (tenant_id,)).fetchall()


def decide_change(conn, *, actor, request_id: int, approve: bool, note: str = "",
                  tenant_id: str = PLATFORM_TENANT) -> dict:
    _require_admin(actor)
    with conn.transaction():
        req = conn.execute("SELECT * FROM config_change_requests WHERE tenant_id = %s AND request_id = %s "
                           "FOR UPDATE", (tenant_id, request_id)).fetchone()
        if req is None:
            raise ConfigError("no such change request")
        if req["status"] != "PENDING":
            raise ConfigError(f"request already {req['status']}")
        if req["proposed_by"] == actor.user_id:
            raise ConfigForbidden("you cannot approve or reject your own config change (R-18)")
        status = "APPROVED" if approve else "REJECTED"
        conn.execute("UPDATE config_change_requests SET status = %s, decided_by = %s, decided_at = now(), "
                     "decision_note = %s WHERE tenant_id = %s AND request_id = %s",
                     (status, actor.user_id, note or None, tenant_id, request_id))
        payload = {"request_id": request_id, "key": req["key"], "old_value": req["old_value"],
                   "new_value": req["new_value"], "reason": req["reason"], "proposed_by": req["proposed_by"],
                   "decided_by": actor.user_id, "note": note or None}
        if approve:
            nxt = conn.execute("SELECT COALESCE(MAX(version),0)+1 AS v FROM config_versions "
                               "WHERE tenant_id = %s AND key = %s", (tenant_id, req["key"])).fetchone()["v"]
            conn.execute("INSERT INTO config_versions (tenant_id, key, value, version, changed_by, reason) "
                         "VALUES (%s,%s,%s::jsonb,%s,%s,%s)",
                         (tenant_id, req["key"], json.dumps(req["new_value"]), nxt, req["proposed_by"],
                          f"{req['reason']} (approved by {actor.user_id})"))
            payload["config_version"] = nxt
        append_event(conn, tenant_id=tenant_id, case_id=None,
                     event_type="CONFIG_CHANGED" if approve else "CONFIG_CHANGE_REJECTED",
                     actor_type=ActorType.HUMAN, actor_id=actor.user_id, actor_role=str(actor.role), payload=payload)
    return {**req, "status": status}
