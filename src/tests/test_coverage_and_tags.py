"""R-26 v0: edge >= 15%, adversarial >= 10%, every listed edge/adversarial case present and tagged."""
import pytest

from synthgen import cli, generator
from synthgen.generator import ADVERSARIAL_TAGS, EDGE_TAGS

REQUIRED_EDGE = {"missing_document", "missing_records", "conflicting_records", "deferral_or_hardship",
                 "repeat", "duplicate", "malformed_input", "multi_issue", "near_deadline",
                 "deadline_breached", "deadline_on_holiday", "doc_unreadable", "months_undetermined"}
REQUIRED_ADV = {"injection_letter_body", "injection_hidden_text", "injection_acdv_free_text",
                "injection_file_metadata", "injection_tool_syntax", "pii_bait", "identity_fraud_disguised"}


@pytest.mark.parametrize("n", [100, 200, 1000])
def test_shares_meet_r26(n):
    s = cli.summarise(generator.generate(11, n)["labels"])
    assert s["edge_case_share"] >= 0.15, s
    assert s["adversarial_share"] >= 0.10, s


@pytest.mark.parametrize("n", [200, 1000])
def test_every_required_tag_present(n):
    s = cli.summarise(generator.generate(11, n)["labels"])
    assert REQUIRED_EDGE <= set(s["edge_tags"]), REQUIRED_EDGE - set(s["edge_tags"])
    assert REQUIRED_ADV <= set(s["adversarial_tags"]), REQUIRED_ADV - set(s["adversarial_tags"])


def test_tags_are_from_closed_lists(batch):
    for l in batch["labels"]:
        assert set(l["edge_tags"]) <= EDGE_TAGS
        assert set(l["adversarial_tags"]) <= ADVERSARIAL_TAGS


def test_payment_history_mix_has_verify_modify_escalate(batch):
    ph = [l for l in batch["labels"] if l["categories"] == ["PAYMENT_HISTORY"]]
    outs = {l["gold"]["outcome"] for l in ph}
    assert {"VERIFIED_AS_REPORTED", "MODIFY", "ESCALATED"} <= outs


def test_balance_is_classify_only(batch):
    for l in batch["labels"]:
        if l["categories"] == ["BALANCE"]:
            assert l["gold"]["outcome"] in ("OUT_OF_SCOPE", "ESCALATED", "DUPLICATE_IGNORED")
            assert not l["gold"]["month_results"]


def test_injection_markers_present_on_their_surface(batch):
    for e, l in zip(batch["acdvs"], batch["labels"]):
        tags = set(l["adversarial_tags"])
        a = e["acdv"]
        letter = a["attachments"][0] if a["attachments"] else None
        if "injection_letter_body" in tags:
            assert "SYSTEM:" in letter["extracted_text"] and l["suspicious_expected"] == "HIGH"
        if "injection_acdv_free_text" in tags:
            assert "assistant:" in a["free_text"] and l["suspicious_expected"] == "HIGH"
        if "injection_hidden_text" in tags:
            assert letter["render_hints"]["hidden_spans"] and "​" in letter["extracted_text"]
            assert l["suspicious_expected"] == "HIGH"
        if "injection_file_metadata" in tags:
            assert "IGNORE_PREVIOUS" in letter["file_name"] and "SYSTEM:" in letter["metadata"]["title"]
        if "injection_tool_syntax" in tags:
            assert '"tool"' in letter["extracted_text"] and l["suspicious_expected"] == "LOW"
        if not tags & {t for t in ADVERSARIAL_TAGS if t.startswith("injection")}:
            assert l["suspicious_expected"] == "NONE"


def test_imperative_negative_control_not_suspicious(batch):
    ctl = [l for l in batch["labels"] if "imperative_negative_control" in l["other_tags"]]
    assert ctl and all(l["suspicious_expected"] == "NONE" for l in ctl)


def test_injection_never_changes_gold(batch):
    """Gold outcome for injected cases equals the scenario intent (outcome is rules-only)."""
    for l in batch["labels"]:
        if any(t.startswith("injection") for t in l["adversarial_tags"]):
            assert l["gold"]["outcome"] == "VERIFIED_AS_REPORTED"


def test_small_n_rejected():
    with pytest.raises(ValueError):
        generator.generate(1, 20)
