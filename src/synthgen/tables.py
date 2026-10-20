"""Load the versioned placeholder reference tables (R-35 format: verified + source)."""
from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

TABLE_DIR = Path(__file__).parent / "reference_tables"
REQUIRED_KEYS = ("table_id", "table_version", "verified", "source", "entries")


@lru_cache(maxsize=None)
def load(table_id: str) -> dict:
    data = json.loads((TABLE_DIR / f"{table_id}.json").read_text(encoding="utf-8"))
    missing = [k for k in REQUIRED_KEYS if k not in data]
    if missing:
        raise ValueError(f"table {table_id} missing keys {missing}")
    return data


def all_tables() -> dict[str, dict]:
    return {p.stem: load(p.stem) for p in sorted(TABLE_DIR.glob("*.json"))}


def table_versions() -> dict[str, dict]:
    return {k: {"version": v["table_version"], "verified": v["verified"]} for k, v in all_tables().items()}


def rating_for_dpd(dpd: int) -> str:
    for e in load("payment_rating_map")["entries"]:
        if e["dpd_min"] <= dpd <= e["dpd_max"]:
            return e["rating"]
    raise ValueError(f"no rating for dpd={dpd}")


def codes_for(category: str) -> list[str]:
    return [e["code"] for e in load("dispute_code_map")["entries"] if category in e["categories"]]


def categories_for_code(code: str) -> list[str]:
    for e in load("dispute_code_map")["entries"]:
        if e["code"] == code:
            return list(e["categories"])
    return []
