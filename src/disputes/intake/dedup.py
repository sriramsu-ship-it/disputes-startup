"""R-04 duplicates and repeats. OWNER: intake agent. Pure logic over prior cases (the
workflow layer fetches them with db.repo.prior_cases_for_account)."""
from __future__ import annotations

from datetime import date, datetime


def _as_date(v) -> date | None:
    if isinstance(v, datetime):
        return v.date()
    if isinstance(v, date):
        return v
    if isinstance(v, str):
        try:
            return date.fromisoformat(v.strip()[:10])
        except ValueError:
            return None
    return None


def _cats(v) -> set[str]:
    if isinstance(v, str):
        # tolerate a Postgres array literal like "{A,B}"
        v = [x for x in v.strip("{}").split(",") if x]
    if not isinstance(v, (list, tuple, set, frozenset)):
        return set()
    return {str(x) for x in v}


def find_repeat(*, date_received: date, categories: set[str], prior_cases: list[dict],
                window_days: int) -> dict | None:
    """Return the most recent prior case (dict from repo.prior_cases_for_account) on the same
    account whose categories intersect `categories` and whose date_received is within
    `window_days` before `date_received`; else None. Repeat key = account + category.

    "Within" is inclusive at both ends: 0 <= (date_received - prior.date_received).days <= window_days.
    A prior case received on the same day counts (it was ingested earlier, or it would not be a
    prior case). Prior cases dated after `date_received`, without a parseable date, or without
    categories (not yet classified) are ignored. Ties on date keep the first in input order
    (repo returns newest first). The account filter is the caller's query; if a dict carries an
    `account_number`, it is not re-checked here because the signature has no account argument.
    """
    received = _as_date(date_received)
    wanted = {str(c) for c in (categories or ())}
    if received is None or not wanted or window_days < 0:
        return None
    best, best_date = None, None
    for pc in prior_cases or ():
        if not isinstance(pc, dict):
            continue
        d = _as_date(pc.get("date_received"))
        if d is None:
            continue
        age = (received - d).days
        if not 0 <= age <= window_days:
            continue
        if not (_cats(pc.get("categories")) & wanted):
            continue
        if best_date is None or d > best_date:
            best, best_date = pc, d
    return best
