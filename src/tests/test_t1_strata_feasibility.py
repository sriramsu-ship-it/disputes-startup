"""Stage 0 check for the PM: can the generator reach the PRD Appendix B T1 minimum strata?
This is a FEASIBILITY probe of generator v0, not the frozen T1 set (Stage 4)."""
from synthgen import generator

T1_PROBE_MIX = [
    ("ph_modify", 0.20), ("ph_claim_unresolved", 0.08), ("ph_claim_month_extends", 0.05),
    ("ph_evidence_missing", 0.06), ("ph_evidence_conflict", 0.06), ("ph_months_undetermined", 0.02),
    ("missing_document", 0.03), ("multi_issue", 0.02), ("class_conflict", 0.02),
    ("fraud_disguised", 0.15), ("ph_verify_note_near_miss", 0.04), ("imperative_control", 0.02),
    ("_injection_pair", 0.02),
]


def test_t1_minimum_strata_reachable():
    labels = generator.generate(424242, 1100, mix=T1_PROBE_MIX)["labels"]
    should_not_verify = [l for l in labels if l["gold"]["outcome"] in ("MODIFY", "ESCALATED")]
    should_escalate = [l for l in labels if l["gold"]["outcome"] == "ESCALATED"]
    fraud = [l for l in labels if "ID_FRAUD_SUSPECTED" in l["gold"]["escalation_reasons"]]
    clean_verify = [l for l in labels if l["gold"]["outcome"] == "VERIFIED_AS_REPORTED"
                    and not l["adversarial_tags"] and not l["edge_tags"]]
    counts = dict(snv=len(should_not_verify), esc=len(should_escalate), fraud=len(fraud), clean=len(clean_verify))
    print(counts)
    assert counts["snv"] >= 600 and counts["esc"] >= 150 and counts["fraud"] >= 150 and counts["clean"] >= 200, counts


def test_fraud_phrasing_variety_is_low_in_v0():
    """Known v0 limitation reported to the PM: few distinct fraud phrasings, so a >=150 fraud stratum
    would be near-duplicates. Generator v1 (Stage 2) must add variety before T1 is frozen."""
    labels = generator.generate(424242, 1100, mix=T1_PROBE_MIX)["labels"]
    quotes = {c["quote"] for l in labels if "identity_fraud_disguised" in l["adversarial_tags"] for c in l["claims"]}
    assert len(quotes) <= len(generator.FRAUD_LINES)
