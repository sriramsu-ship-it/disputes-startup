"""R-35 reference-table gate (ADR-013). OWNER: rules agent."""
from __future__ import annotations

from disputes.config import Config


class UnverifiedTables(RuntimeError):
    pass


def check_tables(cfg: Config) -> dict[str, dict]:
    """Every table must carry `verified` and `source`. In cfg.mode == "live", raise
    UnverifiedTables if any table is verified=false. Returns reference.versions()."""
    raise NotImplementedError
