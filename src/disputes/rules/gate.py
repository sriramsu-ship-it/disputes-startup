"""R-35 reference-table gate (ADR-010 §2, ADR-013 intent). OWNER: rules agent.

Every reference table must carry a boolean `verified` and a non-empty `source`. The app
refuses to run in "live" (non-synthetic) mode while any table is `verified=false`; in
"synthetic" mode unverified placeholders are allowed and their versions are returned for the
audit payload (R-21, R-22). Any other mode string is refused (fail safe: a typo must not
silently run as live or as synthetic).
"""
from __future__ import annotations

from disputes import reference
from disputes.config import Config

KNOWN_MODES = ("synthetic", "live")


class UnverifiedTables(RuntimeError):
    pass


class MalformedTable(RuntimeError):
    """A table lacks a boolean `verified` or a non-empty `source` (R-35 format)."""


def _check_format(tables: dict[str, dict]) -> None:
    bad = []
    for tid, t in tables.items():
        if not isinstance(t.get("verified"), bool):
            bad.append(f"{tid}: `verified` must be a boolean, got {t.get('verified')!r}")
        src = t.get("source")
        if not isinstance(src, str) or not src.strip():
            bad.append(f"{tid}: `source` must be a non-empty string")
        if t.get("table_id") != tid:
            bad.append(f"{tid}: table_id {t.get('table_id')!r} does not match file name")
    if bad:
        raise MalformedTable("; ".join(bad))


def check_tables(cfg: Config, tables: dict[str, dict] | None = None) -> dict[str, dict]:
    """Every table must carry `verified` and `source`. In cfg.mode == "live", raise
    UnverifiedTables if any table is verified=false. Returns reference.versions().

    `tables` is injectable for tests; by default every table under the reference search path.
    """
    if cfg.mode not in KNOWN_MODES:
        raise ValueError(f"unknown mode {cfg.mode!r}; expected one of {KNOWN_MODES}")
    injected = tables is not None
    tables = tables if injected else reference.all_tables()
    if not tables:
        raise MalformedTable("no reference tables found")
    _check_format(tables)
    if cfg.mode == "live":
        unverified = sorted(tid for tid, t in tables.items() if t["verified"] is not True)
        if unverified:
            raise UnverifiedTables(
                "live mode refused: unverified reference tables " + ", ".join(unverified)
                + " (R-35; verify from the partner guide / CDIA CRRG / counsel first)")
    if injected:
        return {tid: {"version": t["table_version"], "verified": t["verified"]} for tid, t in sorted(tables.items())}
    return reference.versions(*sorted(tables))
