"""Every record validates against its JSON Schema and is marked synthetic."""
import json
from pathlib import Path

import jsonschema
import pytest

from synthgen import tables

SCHEMAS = Path(__file__).resolve().parents[1] / "synthgen" / "schemas"


def _validator(name):
    s = json.loads((SCHEMAS / f"{name}.schema.json").read_text())
    jsonschema.Draft202012Validator.check_schema(s)
    return jsonschema.Draft202012Validator(s)


def test_envelopes_valid(batch):
    v = _validator("acdv_envelope")
    errs = [(e["case_id"], err.message) for e in batch["acdvs"] for err in v.iter_errors(e)]
    assert errs == []


def test_accounts_valid(batch):
    v = _validator("sor_account")
    assert [err.message for a in batch["accounts"] for err in v.iter_errors(a)] == []


def test_labels_valid(batch):
    v = _validator("label")
    assert [(l["case_id"], err.message) for l in batch["labels"] for err in v.iter_errors(l)] == []


def test_every_record_synthetic_true(batch, trial):
    def walk(o):
        if isinstance(o, dict):
            yield o
            for x in o.values():
                yield from walk(x)
        elif isinstance(o, list):
            for x in o:
                yield from walk(x)
    for data in (batch, trial):
        for e in data["acdvs"]:
            assert e["synthetic"] is True and e["acdv"]["synthetic"] is True
            assert e["acdv"]["consumer"]["synthetic"] is True
            for att in e["acdv"]["attachments"]:
                assert att["synthetic"] is True
        for a in data["accounts"]:
            assert a["synthetic"] is True
            for sub in a["transactions"] + a["notes"] + a["free_text_notes"]:
                assert sub["synthetic"] is True
        for l in data["labels"]:
            assert l["synthetic"] is True


def test_schema_rejects_non_synthetic(batch):
    import copy
    v = _validator("acdv_envelope")
    e = copy.deepcopy(batch["acdvs"][0])
    e["acdv"]["synthetic"] = False
    assert list(v.iter_errors(e))


def test_reference_tables_format_and_unverified():
    v = _validator("reference_table")
    ts = tables.all_tables()
    assert set(ts) == {"dispute_code_map", "payment_rating_map", "holiday_calendar", "time_zone"}
    for tid, t in ts.items():
        assert list(v.iter_errors(t)) == [], tid
        assert t["verified"] is False, f"{tid} must stay verified=false until sourced (R-35)"
        assert t.get("synthetic_placeholder") is True


def test_rating_map_is_total_and_non_overlapping():
    e = sorted(tables.load("payment_rating_map")["entries"], key=lambda x: x["dpd_min"])
    assert e[0]["dpd_min"] == 0
    for a, b in zip(e, e[1:]):
        assert b["dpd_min"] == a["dpd_max"] + 1
    for dpd in range(0, 400):
        tables.rating_for_dpd(dpd)


def test_placeholder_codes_not_shaped_like_real_codes():
    for e in tables.load("dispute_code_map")["entries"]:
        assert e["code"].startswith("PLH-")
