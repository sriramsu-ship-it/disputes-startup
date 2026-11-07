"""R-04 duplicates and repeats. OWNER: intake agent. Pure logic over prior cases (the
workflow layer fetches them with db.repo.prior_cases_for_account)."""
from __future__ import annotations

from datetime import date


def find_repeat(*, date_received: date, categories: set[str], prior_cases: list[dict],
                window_days: int) -> dict | None:
    """Return the most recent prior case (dict from repo.prior_cases_for_account) on the same
    account whose categories intersect `categories` and whose date_received is within
    `window_days` before `date_received`; else None. Repeat key = account + category.
    """
    raise NotImplementedError
