"""No field looks like a real SSN or payment card number; detectors themselves work."""
import json
import random
import re

from hypothesis import given, strategies as st

from synthgen import pii_guard, vocab


def _all_text(data):
    return json.dumps(data, ensure_ascii=False)


def test_no_real_looking_pii_in_batch(batch):
    assert pii_guard.find_real_looking_pii(_all_text(batch)) == []


def test_no_real_looking_pii_in_trial(trial):
    assert pii_guard.find_real_looking_pii(_all_text(trial)) == []


def test_no_real_looking_pii_in_trial_files():
    from pathlib import Path
    d = Path(__file__).resolve().parents[1] / "data" / "stage0_trial"
    for f in d.iterdir():
        if f.is_file():
            assert pii_guard.find_real_looking_pii(f.read_text(encoding="utf-8")) == [], f.name


def test_detector_catches_plausible_ssn_and_card():
    # Detector self-test with obviously-constructed values (not real people).
    assert pii_guard.find_real_looking_pii("ssn 123-45-6789")
    assert pii_guard.find_real_looking_pii("card 4111 1111 1111 1111")  # well-known test PAN, passes Luhn
    assert not pii_guard.find_real_looking_pii("ssn 912-00-1234")
    assert not pii_guard.find_real_looking_pii("ssn 666-12-3456")
    assert pii_guard.find_real_looking_pii("my ssn is 123456789.")          # bare 9 digits
    assert not pii_guard.find_real_looking_pii("sha a216558005b")           # inside a hex hash


@given(st.integers(min_value=0, max_value=2**32))
def test_synthetic_ssn_never_assignable(seed):
    s = pii_guard.synthetic_ssn(random.Random(seed))
    a, g, ser = re.match(r"^(\d{3})-(\d{2})-(\d{4})$", s).groups()
    assert not pii_guard.ssn_possibly_real(a, g, ser)


@given(st.integers(min_value=0, max_value=2**32))
def test_bait_card_fails_luhn(seed):
    c = pii_guard.bait_card_number(random.Random(seed)).replace(" ", "")
    assert len(c) == 16 and not pii_guard.luhn_ok(c)


def test_pii_bait_cases_contain_bait(batch):
    bait = [(e, l) for e, l in zip(batch["acdvs"], batch["labels"]) if "pii_bait" in l["adversarial_tags"]]
    assert bait
    for e, _ in bait:
        t = e["acdv"]["attachments"][0]["extracted_text"]
        assert "Social Security number" in t and "card, number" in t and "neighbour" in t


def test_obviously_synthetic_markers(batch):
    for e in batch["acdvs"]:
        a = e["acdv"]
        assert a["consumer"]["last_name"].strip() == "" or a["consumer"]["last_name"] in vocab.SURNAMES
        assert a["consumer"]["address"]["state"] == "ZZ"
        assert a["cra"].startswith("SYNTH-CRA-")
    for acct in batch["accounts"]:
        assert acct["furnisher"].endswith("(SYNTHETIC)")
        assert acct["account_number"].startswith("SYNACCT")
