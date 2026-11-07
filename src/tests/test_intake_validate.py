"""R-02 / R-05 intake validation (intake module)."""
from dataclasses import replace

import pytest

from disputes.domain import EscalationReason
from disputes.intake.validate import parse_iso_date, validate_dispute
from test_intake_helpers import make_dispute

INVALID = (EscalationReason.INTAKE_INVALID,)


def test_valid_dispute_has_no_escalation():
    assert validate_dispute(make_dispute()) == ((), ())


@pytest.mark.parametrize("field", ["control_number", "cra", "date_received", "response_due_date",
                                   "account_number", "consumer_name"])
@pytest.mark.parametrize("bad", [None, "", "   ", "\t\n"])
def test_missing_empty_or_blank_required_field(field, bad):
    esc, errs = validate_dispute(replace(make_dispute(), **{field: bad}))
    assert esc == INVALID
    assert any(e.startswith(field) for e in errs)


def test_missing_due_date_is_intake_invalid():   # R-05 / S1
    esc, errs = validate_dispute(replace(make_dispute(), response_due_date=None))
    assert esc == INVALID and errs == ("response_due_date: missing",)


@pytest.mark.parametrize("bad", ["11/05/2026", "2026-13-01", "2026-02-30", "2026-1-5", "20261105",
                                 " 2026-11-05", "2026-11-05T00:00:00", "2026-11-05Z", "２０２６-11-05", "٢٠٢٦-11-05"])
def test_unparseable_dates(bad):
    for field in ("date_received", "response_due_date"):
        esc, errs = validate_dispute(replace(make_dispute(), **{field: bad}))
        assert esc == INVALID, (field, bad)
        assert "ISO 8601" in errs[0] or "empty" in errs[0]


@pytest.mark.parametrize("codes", [(), ("",), ("PLH-PH-01", "  "), None, "PLH-PH-01x"])
def test_dispute_codes_missing_or_blank(codes):
    esc, _ = validate_dispute(replace(make_dispute(), dispute_codes=codes))
    assert esc == INVALID


def test_free_text_and_attachments_may_be_empty():
    assert validate_dispute(replace(make_dispute(), free_text=None, attachments=())) == ((), ())
    assert validate_dispute(replace(make_dispute(), free_text="")) == ((), ())


def test_non_string_values_do_not_raise():
    d = replace(make_dispute(), control_number=12345, date_received=object(), consumer_name=["x"])
    esc, errs = validate_dispute(d)
    assert esc == INVALID and len(errs) == 3


def test_object_without_fields_does_not_raise():
    esc, errs = validate_dispute(object())
    assert esc == INVALID and errs


def test_errors_never_echo_values():
    d = replace(make_dispute(), account_number="   ", response_due_date="11/05/2026")
    _, errs = validate_dispute(d)
    assert all("11/05/2026" not in e for e in errs)


def test_parse_iso_date():
    assert str(parse_iso_date("2026-02-28")) == "2026-02-28"
    assert parse_iso_date("2026-02-29") is None
    assert parse_iso_date(None) is None
