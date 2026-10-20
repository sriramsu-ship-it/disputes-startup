"""Business-day helper used ONLY to construct labelled deadline fixtures.

This is not the R-05 production clock (Stage 1). Calendar = placeholder holiday
table (verified=false, U21): weekends plus observed 5 USC 6103 holidays.
"""
from __future__ import annotations

from datetime import date, timedelta

from . import tables


def holidays() -> set[date]:
    return {date.fromisoformat(e["observed_date"]) for e in tables.load("holiday_calendar")["entries"]}


def is_business_day(d: date) -> bool:
    return d.weekday() < 5 and d not in holidays()


def add_business_days(d: date, n: int) -> date:
    step = 1 if n >= 0 else -1
    remaining = abs(n)
    cur = d
    while remaining:
        cur += timedelta(days=step)
        if is_business_day(cur):
            remaining -= 1
    return cur


def business_days_between(a: date, b: date) -> int:
    """Count business days in (a, b]; negative if b < a."""
    if b == a:
        return 0
    sign = 1 if b > a else -1
    lo, hi = (a, b) if b > a else (b, a)
    n, cur = 0, lo
    while cur < hi:
        cur += timedelta(days=1)
        if is_business_day(cur):
            n += 1
    return sign * n


def clock_state(as_of: date, due: date, target_offset_bd: int = 3, at_risk_bd: int = 2) -> str:
    """PRD R-05 states, evaluated on calendar dates (end-of-day zone ignored at day granularity)."""
    if as_of > due:
        return "BREACHED"
    target = add_business_days(due, -target_offset_bd)
    if as_of >= add_business_days(target, -at_risk_bd):
        return "AT_RISK"
    return "ON_TRACK"
