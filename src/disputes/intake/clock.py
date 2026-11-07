"""R-05 deadline clock. OWNER: intake agent.

Pure functions; the holiday calendar and time zone come from reference tables
(disputes.reference.load), both verified=false placeholders (U21). No statutory deadline is
computed from memory (ADR-010): we store the CRA-provided due date and derive the internal target.
"""
from __future__ import annotations

from datetime import date, datetime

from disputes.config import Config
from disputes.domain import ClockInfo


def is_business_day(d: date) -> bool:
    """Weekdays that are not in the holiday table."""
    raise NotImplementedError


def subtract_business_days(d: date, n: int) -> date:
    raise NotImplementedError


def business_days_between(start: date, end: date) -> int:
    """Signed count of business days from start (exclusive) to end (inclusive)."""
    raise NotImplementedError


def compute_clock(due_date: date, now: datetime, cfg: Config) -> ClockInfo:
    """R-05. internal_target = due_date minus cfg.internal_target_business_days_before_due business days.
    Evaluate 'now' in the configured time zone; deadlines end at end of day in that zone.
    ON_TRACK until AT_RISK; AT_RISK from cfg.at_risk_business_days_before_target business days
    before the internal target until the due date ends; BREACHED after the due date ends.
    `now` must be timezone-aware. table_versions records the holiday/time-zone table versions.
    """
    raise NotImplementedError
