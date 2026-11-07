"""Global-head anchor (ADR-003 §5, R-21). OWNER: platform-core.

`write_anchor` records {global_head_event_id, global_hash, at} as a write-once JSON file
(opened O_EXCL so an existing anchor is never overwritten, then chmod 0444).

LOCAL STAND-IN: production needs an object-locked bucket (compliance-mode retention >= audit
retention) that the database superuser cannot write to. A local directory on the same host
does NOT give that guarantee (anyone with filesystem rights can delete or edit it); it only
exercises the format and the `verify` comparison. Schedule: every cfg.anchor_interval_min
minutes (default 15) via `python -m disputes.cli anchor` from cron/systemd; no scheduler is
built in the prototype.
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path

from disputes.audit.chain import GENESIS, rfc3339

ANCHOR_GLOB = "anchor-*.json"


class AnchorExists(FileExistsError):
    pass


def write_anchor(conn, anchor_dir) -> dict:
    """Write the current global head as a new write-once anchor file. Returns the anchor dict
    plus `path`. An empty log anchors event 0 with the genesis hash."""
    row = conn.execute("SELECT event_id, global_hash FROM audit_events ORDER BY event_id DESC LIMIT 1").fetchone()
    head_id, head_hash = (row["event_id"], row["global_hash"]) if row else (0, GENESIS)
    at = rfc3339(datetime.now(timezone.utc))
    anchor = {"global_head_event_id": head_id, "global_hash": head_hash, "at": at}
    d = Path(anchor_dir)
    d.mkdir(parents=True, exist_ok=True)
    stamp = at.replace("-", "").replace(":", "").replace(".", "")
    path = d / f"anchor-{head_id:012d}-{stamp}.json"
    try:
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o444)
    except FileExistsError as e:
        raise AnchorExists(f"anchor {path} already exists; anchors are write-once") from e
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump(anchor, f, sort_keys=True)
    os.chmod(path, 0o444)
    return {**anchor, "path": str(path)}


def list_anchors(anchor_dir) -> list[dict]:
    d = Path(anchor_dir)
    if not d.exists():
        return []
    out = []
    for p in sorted(d.glob(ANCHOR_GLOB)):
        a = json.loads(p.read_text(encoding="utf-8"))
        a["path"] = str(p)
        out.append(a)
    return sorted(out, key=lambda a: (int(a["global_head_event_id"]), a["at"]))


def latest_anchor(anchor_dir) -> dict | None:
    """The anchor with the highest head event id (latest `at` on ties), or None."""
    anchors = list_anchors(anchor_dir)
    return anchors[-1] if anchors else None
