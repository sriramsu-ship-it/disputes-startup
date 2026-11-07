"""Reference tables (R-35 format: table_id, table_version, verified, source, entries).

Search order: disputes/reference_tables/ (platform tables, e.g. injection_patterns,
fraud_keywords, outcome_words, response_templates) then synthgen/reference_tables/ (Stage 0
placeholders: dispute_code_map, payment_rating_map, holiday_calendar, time_zone).
The R-35 start-up gate lives in rules/gate.py.
"""
from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

_SRC = Path(__file__).resolve().parent.parent
TABLE_DIRS = (Path(__file__).parent / "reference_tables", _SRC / "synthgen" / "reference_tables")
REQUIRED_KEYS = ("table_id", "table_version", "verified", "source", "entries")


class TableError(ValueError):
    pass


@lru_cache(maxsize=None)
def load(table_id: str) -> dict:
    for d in TABLE_DIRS:
        p = d / f"{table_id}.json"
        if p.exists():
            data = json.loads(p.read_text(encoding="utf-8"))
            missing = [k for k in REQUIRED_KEYS if k not in data]
            if missing:
                raise TableError(f"table {table_id} missing keys {missing}")
            return data
    raise TableError(f"no reference table {table_id!r}")


def all_tables() -> dict[str, dict]:
    ids = sorted({p.stem for d in TABLE_DIRS if d.exists() for p in d.glob("*.json")})
    return {i: load(i) for i in ids}


def versions(*table_ids: str) -> dict[str, dict]:
    """{table_id: {"version": ..., "verified": ...}} for audit payloads (R-21, R-22)."""
    ids = table_ids or tuple(all_tables())
    return {i: {"version": load(i)["table_version"], "verified": load(i)["verified"]} for i in ids}
