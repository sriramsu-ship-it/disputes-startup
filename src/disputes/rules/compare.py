"""R-09 deterministic per-month comparison. OWNER: rules agent."""
from __future__ import annotations

from disputes import reference
from disputes.domain import Evidence, MonthComparison, MonthResult

RATING_TABLE = "payment_rating_map"


def expected_rating(dpd, table: dict | None = None) -> str | None:
    """DPD -> rating via the versioned table; None if DPD is not a non-negative int or no bucket matches."""
    if isinstance(dpd, bool) or not isinstance(dpd, int) or dpd < 0:
        return None
    t = table if table is not None else reference.load(RATING_TABLE)
    hits = [e["rating"] for e in t["entries"] if e["dpd_min"] <= dpd <= e["dpd_max"]]
    return hits[0] if len(hits) == 1 else None   # 0 or overlapping buckets -> undetermined


def compare_months(months: list[str], evidence: list[Evidence]) -> list[MonthComparison]:
    """For each disputed month: DPD at cycle date (from EV-CYCLE-<month>) -> expected rating via
    the `payment_rating_map` table; compare with the reported rating. MATCH / MISMATCH, or
    NO_DATA if the cycle is missing or DPD/rating is absent. Cite the cycle evidence ID.

    A missing cycle cites EV-ACCOUNT when the account was retrieved (the record that lacks the
    month), otherwise nothing. Output is one row per distinct month, sorted."""
    by_id = {e.evidence_id: e for e in evidence}
    out: list[MonthComparison] = []
    for m in sorted(set(months)):
        ev = by_id.get(f"EV-CYCLE-{m}")
        if ev is None:
            cite = ("EV-ACCOUNT",) if "EV-ACCOUNT" in by_id else ()
            out.append(MonthComparison(m, None, None, None, MonthResult.NO_DATA, cite))
            continue
        c = ev.content
        dpd = c.get("dpd_at_cycle")
        dpd = dpd if isinstance(dpd, int) and not isinstance(dpd, bool) else None
        reported = c.get("reported_rating")
        reported = reported if isinstance(reported, str) and reported else None
        exp = expected_rating(dpd)
        if exp is None or reported is None:
            res = MonthResult.NO_DATA
        else:
            res = MonthResult.MATCH if exp == reported else MonthResult.MISMATCH
        out.append(MonthComparison(m, dpd, exp, reported, res, (ev.evidence_id,)))
    return out
