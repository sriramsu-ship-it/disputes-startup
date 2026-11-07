"""R-05 deadline clock. OWNER: intake agent.

Pure functions; the holiday calendar and time zone come from reference tables
(disputes.reference.load), both verified=false placeholders (U21). No statutory deadline is
computed from memory (ADR-010): we store the CRA-provided due date and derive the internal target.

Conventions (PRD R-05, ADR-010):
- Business day = Monday-Friday and not an `observed_date` in `holiday_calendar` (U21, U36).
- A due date is NOT shifted when it falls on a weekend/holiday (no rule for that exists, U36);
  the internal target is counted back from the CRA date as given.
- "End of day" = midnight at the end of that calendar date in the configured zone
  (`time_zone.due_date_end_of_day_zone`). `now` is converted to that zone and its local date is
  used for every comparison.
- AT_RISK starts at the beginning of the local day that is `at_risk_business_days_before_target`
  business days before the internal target, and lasts until the due date ends (this covers
  "past the target but not yet due"). BREACHED once the due date has ended.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta
from functools import lru_cache
from zoneinfo import ZoneInfo

from disputes import reference
from disputes.config import Config
from disputes.domain import ClockInfo, ClockState

HOLIDAY_TABLE = "holiday_calendar"
TZ_TABLE = "time_zone"
TZ_KEY = "due_date_end_of_day_zone"
RULE_ID = "R-05.CLOCK"
RULE_VERSION = "1.0.0"


# ----------------------------------------------------------------------------- tables
@lru_cache(maxsize=None)
def _holidays_for(version: str) -> frozenset[date]:
    t = reference.load(HOLIDAY_TABLE)
    return frozenset(date.fromisoformat(e["observed_date"]) for e in t["entries"])


def holidays() -> frozenset[date]:
    t = reference.load(HOLIDAY_TABLE)
    return _holidays_for(t["table_version"])


def calendar_covers(d: date) -> bool:
    """True if `d` lies inside the holiday table's effective range. Outside it, only weekends
    are excluded, which may overstate business days (reported in ClockInfo.table_versions)."""
    t = reference.load(HOLIDAY_TABLE)
    lo, hi = t.get("effective_from"), t.get("effective_to")
    if not lo or not hi:
        return True
    return date.fromisoformat(lo) <= d <= date.fromisoformat(hi)


def zone() -> ZoneInfo:
    for e in reference.load(TZ_TABLE)["entries"]:
        if e.get("key") == TZ_KEY:
            return ZoneInfo(e["value"])
    raise reference.TableError(f"{TZ_TABLE} has no {TZ_KEY!r} entry")


# ----------------------------------------------------------------------------- arithmetic
def is_business_day(d: date) -> bool:
    """Weekdays that are not in the holiday table."""
    return d.weekday() < 5 and d not in holidays()


def add_business_days(d: date, n: int) -> date:
    """Move n business days forward (n<0: backward). n == 0 returns d unchanged, even if d is not
    a business day. For n != 0 the result is always a business day."""
    step = 1 if n >= 0 else -1
    remaining = abs(n)
    cur = d
    while remaining:
        cur += timedelta(days=step)
        if is_business_day(cur):
            remaining -= 1
    return cur


def subtract_business_days(d: date, n: int) -> date:
    return add_business_days(d, -n)


def business_days_between(start: date, end: date) -> int:
    """Signed count of business days from start (exclusive) to end (inclusive).
    If end < start, minus the count of business days in (end, start]."""
    if end == start:
        return 0
    sign = 1 if end > start else -1
    lo, hi = (start, end) if end > start else (end, start)
    hol = holidays()
    # Whole weeks fast path: 5 weekdays per 7 days, then subtract holidays in range.
    days = (hi - lo).days
    weeks, rem = divmod(days, 7)
    n = weeks * 5
    cur = lo + timedelta(days=weeks * 7)
    for _ in range(rem):
        cur += timedelta(days=1)
        if cur.weekday() < 5:
            n += 1
    n -= sum(1 for h in hol if lo < h <= hi and h.weekday() < 5)
    return sign * n


# ----------------------------------------------------------------------------- clock
def end_of_day(d: date) -> datetime:
    """The instant the local calendar day `d` ends in the configured zone (next local midnight)."""
    return datetime.combine(d + timedelta(days=1), datetime.min.time(), tzinfo=zone())


def compute_clock(due_date: date, now: datetime, cfg: Config) -> ClockInfo:
    """R-05. internal_target = due_date minus cfg.internal_target_business_days_before_due business days.
    Evaluate 'now' in the configured time zone; deadlines end at end of day in that zone.
    ON_TRACK until AT_RISK; AT_RISK from cfg.at_risk_business_days_before_target business days
    before the internal target until the due date ends; BREACHED after the due date ends.
    `now` must be timezone-aware. table_versions records the holiday/time-zone table versions.
    """
    if not isinstance(now, datetime) or now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("compute_clock: `now` must be a timezone-aware datetime")
    if isinstance(due_date, datetime) or not isinstance(due_date, date):
        raise ValueError("compute_clock: `due_date` must be a date")
    if cfg.internal_target_business_days_before_due < 0 or cfg.at_risk_business_days_before_target < 0:
        raise ValueError("compute_clock: business-day offsets must be >= 0")

    tz = zone()
    today = now.astimezone(tz).date()
    target = subtract_business_days(due_date, cfg.internal_target_business_days_before_due)
    at_risk_from = subtract_business_days(target, cfg.at_risk_business_days_before_target)

    if now >= end_of_day(due_date):          # same as today > due_date in the configured zone
        state = ClockState.BREACHED
    elif today >= at_risk_from:
        state = ClockState.AT_RISK
    else:
        state = ClockState.ON_TRACK

    versions = reference.versions(HOLIDAY_TABLE, TZ_TABLE)
    versions[HOLIDAY_TABLE] = {**versions[HOLIDAY_TABLE],
                               "covers_dates": all(calendar_covers(x) for x in (today, at_risk_from, due_date))}
    versions[TZ_TABLE] = {**versions[TZ_TABLE], "zone": str(tz)}
    versions["rule"] = {"id": RULE_ID, "version": RULE_VERSION}
    return ClockInfo(
        due_date=due_date,
        internal_target=target,
        state=state,
        evaluated_at=now,
        business_days_to_target=business_days_between(today, target),
        table_versions=versions,
    )
