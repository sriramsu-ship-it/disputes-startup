"""R-05 clock and business-day arithmetic (intake module), incl. hypothesis property tests (T0)."""
from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

import pytest
from hypothesis import given, settings, strategies as st

from disputes import reference
from disputes.config import defaults
from disputes.domain import ClockState
from disputes.intake import clock
from disputes.intake.clock import (add_business_days, business_days_between, compute_clock, is_business_day,
                                   subtract_business_days)
from test_intake_helpers import NY, eod

CFG = defaults()
HOLS = {date.fromisoformat(e["observed_date"]) for e in reference.load("holiday_calendar")["entries"]}
IN_CAL = st.dates(min_value=date(2026, 1, 1), max_value=date(2027, 12, 31))
ANY = st.dates(min_value=date(2024, 1, 1), max_value=date(2029, 12, 31))
PROP = settings(max_examples=400, deadline=None)


def naive_between(a, b):
    sign, lo, hi = (1, a, b) if b >= a else (-1, b, a)
    return sign * sum(1 for i in range(1, (hi - lo).days + 1)
                      if (lo + timedelta(i)).weekday() < 5 and lo + timedelta(i) not in HOLS)


# ----------------------------------------------------------------- unit
def test_holidays_and_weekends():
    assert not is_business_day(date(2026, 11, 11))      # Veterans Day
    assert not is_business_day(date(2026, 7, 3))        # observed Independence Day (Sat -> Fri)
    assert is_business_day(date(2026, 7, 6))
    assert not is_business_day(date(2026, 11, 7))       # Saturday
    assert not is_business_day(date(2026, 11, 8))       # Sunday
    assert is_business_day(date(2026, 11, 9))


def test_subtract_skips_weekend_and_holiday():
    # Due Mon 2026-11-16; minus 3 bd: Fri 13, Thu 12, (Wed 11 Veterans Day skipped) Tue 10
    assert subtract_business_days(date(2026, 11, 16), 3) == date(2026, 11, 10)
    assert subtract_business_days(date(2026, 11, 16), 0) == date(2026, 11, 16)
    assert add_business_days(date(2026, 11, 25), 1) == date(2026, 11, 27)   # Thanksgiving skipped


def test_between_signed_exclusive_inclusive():
    assert business_days_between(date(2026, 11, 9), date(2026, 11, 13)) == 3   # 10, 12, 13 (11 holiday)
    assert business_days_between(date(2026, 11, 13), date(2026, 11, 9)) == -3
    assert business_days_between(date(2026, 11, 9), date(2026, 11, 9)) == 0


def test_internal_target_and_states_s8():
    due = date(2026, 11, 20)                     # Fri
    target = date(2026, 11, 17)                  # Tue (3 bd before)
    at_risk_from = date(2026, 11, 13)            # Fri (2 bd before target; Veterans Day not crossed)
    c = compute_clock(due, eod("2026-11-12"), CFG)
    assert (c.internal_target, c.state) == (target, ClockState.ON_TRACK)
    assert compute_clock(due, datetime.combine(at_risk_from, time(0, 0), NY), CFG).state == ClockState.AT_RISK
    assert compute_clock(due, eod("2026-11-14"), CFG).state == ClockState.AT_RISK      # weekend inside window
    assert compute_clock(due, eod("2026-11-18"), CFG).state == ClockState.AT_RISK      # past target, not yet due
    last = datetime.combine(due, time(23, 59, 59, 999999), NY)
    assert compute_clock(due, last, CFG).state == ClockState.AT_RISK                   # due date has not ended
    assert compute_clock(due, last + timedelta(microseconds=1), CFG).state == ClockState.BREACHED
    assert compute_clock(due, eod("2026-11-12"), CFG).business_days_to_target == 3    # 13, 16, 17


def test_end_of_day_uses_configured_zone_not_utc():
    due = date(2026, 11, 20)
    # 2026-11-21 03:00 UTC is still 2026-11-20 22:00 in New York: not breached.
    assert compute_clock(due, datetime(2026, 11, 21, 3, 0, tzinfo=timezone.utc), CFG).state == ClockState.AT_RISK
    # 2026-11-21 05:00 UTC is 00:00 on the 21st in New York: breached.
    assert compute_clock(due, datetime(2026, 11, 21, 5, 0, tzinfo=timezone.utc), CFG).state == ClockState.BREACHED
    # A Los Angeles evening on the due date is already past NY midnight (errs early).
    la = datetime(2026, 11, 20, 22, 0, tzinfo=ZoneInfo("America/Los_Angeles"))
    assert compute_clock(due, la, CFG).state == ClockState.BREACHED


def test_due_date_already_past_at_intake_is_breached():
    assert compute_clock(date(2026, 10, 9), eod("2026-10-14"), CFG).state == ClockState.BREACHED


def test_due_on_holiday_not_shifted():
    c = compute_clock(date(2026, 12, 25), eod("2026-12-07"), CFG)
    assert c.due_date == date(2026, 12, 25)
    assert c.internal_target == date(2026, 12, 22)
    assert c.state == ClockState.ON_TRACK
    # Evaluated at end of the holiday itself in the configured zone.
    assert compute_clock(date(2026, 12, 25), datetime(2026, 12, 25, 23, 0, tzinfo=NY), CFG).state == ClockState.AT_RISK


def test_config_offsets_respected():
    c = compute_clock(date(2026, 11, 20), eod("2026-11-12"),
                      CFG.with_overrides(internal_target_business_days_before_due=1,
                                         at_risk_business_days_before_target=0))
    assert c.internal_target == date(2026, 11, 19) and c.state == ClockState.ON_TRACK


def test_naive_now_rejected():
    with pytest.raises(ValueError):
        compute_clock(date(2026, 11, 20), datetime(2026, 11, 12, 17, 0), CFG)


def test_table_versions_recorded():
    c = compute_clock(date(2026, 11, 20), eod("2026-11-12"), CFG)
    assert c.table_versions["holiday_calendar"]["version"] == "0.1.0"
    assert c.table_versions["holiday_calendar"]["verified"] is False
    assert c.table_versions["holiday_calendar"]["covers_dates"] is True
    assert c.table_versions["time_zone"]["zone"] == "America/New_York"
    assert c.table_versions["time_zone"]["verified"] is False
    out = compute_clock(date(2028, 3, 10), eod("2028-02-01"), CFG)
    assert out.table_versions["holiday_calendar"]["covers_dates"] is False


# ----------------------------------------------------------------- properties (T0)
@PROP
@given(ANY, st.integers(min_value=1, max_value=60))
def test_prop_never_lands_on_weekend_or_holiday(d, n):
    for r in (subtract_business_days(d, n), add_business_days(d, n)):
        assert r.weekday() < 5 and r not in HOLS


@PROP
@given(ANY, st.integers(min_value=0, max_value=60))
def test_prop_round_trip_counts(d, n):
    back = subtract_business_days(d, n)
    if is_business_day(d):
        assert business_days_between(back, d) == n
        assert add_business_days(back, n) == d
    fwd = add_business_days(d, n)
    assert business_days_between(d, fwd) == n
    if n and is_business_day(d):
        assert subtract_business_days(fwd, n) == d


@PROP
@given(ANY, ANY)
def test_prop_between_matches_naive_and_is_antisymmetric(a, b):
    assert business_days_between(a, b) == naive_between(a, b)
    assert business_days_between(a, b) == -business_days_between(b, a)


@PROP
@given(ANY, ANY, ANY)
def test_prop_between_is_additive(a, b, c):
    assert business_days_between(a, c) == business_days_between(a, b) + business_days_between(b, c)


@PROP
@given(IN_CAL, st.integers(min_value=-40, max_value=40), st.integers(min_value=0, max_value=23),
       st.integers(min_value=0, max_value=3), st.integers(min_value=0, max_value=3))
def test_prop_clock_state_definition(due, offset, hour, tgt, risk):
    cfg = CFG.with_overrides(internal_target_business_days_before_due=tgt, at_risk_business_days_before_target=risk)
    now = datetime.combine(due + timedelta(days=offset), time(hour), NY)
    c = compute_clock(due, now, cfg)
    today = now.date()
    target = subtract_business_days(due, tgt)
    assert c.internal_target == target
    assert c.business_days_to_target == business_days_between(today, target)
    if today > due:
        assert c.state == ClockState.BREACHED
    elif today >= subtract_business_days(target, risk):
        assert c.state == ClockState.AT_RISK
    else:
        assert c.state == ClockState.ON_TRACK
    if tgt >= 1:
        assert is_business_day(target) and target < due


@PROP
@given(IN_CAL, st.integers(min_value=0, max_value=30))
def test_prop_states_are_monotonic_in_time(due, start):
    order = {ClockState.ON_TRACK: 0, ClockState.AT_RISK: 1, ClockState.BREACHED: 2}
    seen = [compute_clock(due, datetime.combine(due - timedelta(days=start - i), time(12), NY), CFG).state
            for i in range(0, start + 3)]
    assert [order[s] for s in seen] == sorted(order[s] for s in seen)
