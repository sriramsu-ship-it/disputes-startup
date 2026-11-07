"""R-04 repeat detection (intake module). Duplicates by control number are a DB lookup in workflow."""
from datetime import date

from disputes.intake.dedup import find_repeat


def pc(cid, d, cats):
    return {"case_id": cid, "date_received": d, "categories": cats, "state": "SUBMITTED_STUB",
            "proposed_outcome": "VERIFIED_AS_REPORTED", "final_outcome": "VERIFIED_AS_REPORTED"}


R = date(2026, 11, 1)


def test_same_category_30_days_earlier_is_repeat_s1():
    p = pc("C1", date(2026, 10, 2), ["PAYMENT_HISTORY"])
    assert find_repeat(date_received=R, categories={"PAYMENT_HISTORY"}, prior_cases=[p], window_days=90) is p


def test_window_boundaries_inclusive():
    on = pc("C90", date(2026, 8, 3), ["PAYMENT_HISTORY"])      # exactly 90 days
    off = pc("C91", date(2026, 8, 2), ["PAYMENT_HISTORY"])     # 91 days
    assert (R - on["date_received"]).days == 90
    assert find_repeat(date_received=R, categories={"PAYMENT_HISTORY"}, prior_cases=[on], window_days=90) is on
    assert find_repeat(date_received=R, categories={"PAYMENT_HISTORY"}, prior_cases=[off], window_days=90) is None
    same_day = pc("C0", R, ["PAYMENT_HISTORY"])
    assert find_repeat(date_received=R, categories={"PAYMENT_HISTORY"}, prior_cases=[same_day], window_days=90) is same_day


def test_category_must_intersect():
    p = pc("C1", date(2026, 10, 2), ["BALANCE"])
    assert find_repeat(date_received=R, categories={"PAYMENT_HISTORY"}, prior_cases=[p], window_days=90) is None
    multi = pc("C2", date(2026, 10, 2), ["BALANCE", "PAYMENT_HISTORY"])
    assert find_repeat(date_received=R, categories={"PAYMENT_HISTORY"}, prior_cases=[p, multi], window_days=90) is multi


def test_most_recent_wins_regardless_of_input_order():
    a = pc("OLD", date(2026, 9, 1), ["PAYMENT_HISTORY"])
    b = pc("NEW", date(2026, 10, 20), ["PAYMENT_HISTORY"])
    for order in ([a, b], [b, a]):
        assert find_repeat(date_received=R, categories={"PAYMENT_HISTORY"}, prior_cases=order, window_days=90) is b


def test_future_unclassified_and_malformed_priors_ignored():
    priors = [pc("F", date(2026, 11, 5), ["PAYMENT_HISTORY"]), pc("U", date(2026, 10, 5), []),
              pc("N", None, ["PAYMENT_HISTORY"]), "junk", {"case_id": "X"}]
    assert find_repeat(date_received=R, categories={"PAYMENT_HISTORY"}, prior_cases=priors, window_days=90) is None
    assert find_repeat(date_received=R, categories=set(), prior_cases=priors, window_days=90) is None
    assert find_repeat(date_received=R, categories={"PAYMENT_HISTORY"}, prior_cases=[], window_days=90) is None


def test_string_dates_and_pg_array_literal_tolerated():
    p = {"case_id": "S", "date_received": "2026-10-02", "categories": "{PAYMENT_HISTORY}"}
    assert find_repeat(date_received=R, categories={"PAYMENT_HISTORY"}, prior_cases=[p], window_days=90) is p


def test_window_is_config():
    p = pc("C1", date(2026, 10, 2), ["PAYMENT_HISTORY"])
    assert find_repeat(date_received=R, categories={"PAYMENT_HISTORY"}, prior_cases=[p], window_days=29) is None
