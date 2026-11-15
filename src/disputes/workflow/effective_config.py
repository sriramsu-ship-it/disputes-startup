"""Shared effective-config loader (web contract request 5). OWNER: hardening (workflow).

Effective config = `config.defaults()` overlaid by the newest `config_versions` row per key for
the platform tenant 'ops'. The pipeline (worker), the clock refresh job and the web all call this
one function, so an ADMIN change approved by a second ADMIN (web/configsvc.py) reaches all of them.
Unknown keys are ignored; a stored value that cannot be coerced to the field's type is ignored
(and the default kept) rather than crashing the worker. `mode` and `llm_model_id` are locked in the
admin UI (R-35 / R-30) and are read here like any other key.
"""
from __future__ import annotations

import logging
from dataclasses import fields

from disputes.config import Config, defaults

PLATFORM_TENANT = "ops"
log = logging.getLogger(__name__)


def config_types() -> dict[str, type]:
    d = defaults()
    return {f.name: type(getattr(d, f.name)) for f in fields(Config)}


def effective_config(conn, tenant_id: str = PLATFORM_TENANT) -> Config:
    with conn.transaction():
        rows = conn.execute(
            "SELECT DISTINCT ON (key) key, value FROM config_versions WHERE tenant_id = %s "
            "ORDER BY key, version DESC", (tenant_id,)).fetchall()
    types = config_types()
    over = {}
    for r in rows:
        t = types.get(r["key"])
        if t is None:
            continue
        try:
            over[r["key"]] = t(r["value"])
        except (TypeError, ValueError):
            log.warning("config_versions %s has a value of the wrong type; default kept", r["key"])
    return defaults().with_overrides(**over)
