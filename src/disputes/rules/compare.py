"""R-09 deterministic per-month comparison. OWNER: rules agent."""
from __future__ import annotations

from disputes.domain import Evidence, MonthComparison


def compare_months(months: list[str], evidence: list[Evidence]) -> list[MonthComparison]:
    """For each disputed month: DPD at cycle date (from EV-CYCLE-<month>) -> expected rating via
    the `payment_rating_map` table; compare with the reported rating. MATCH / MISMATCH, or
    NO_DATA if the cycle is missing or DPD/rating is absent. Cite the cycle evidence ID."""
    raise NotImplementedError
