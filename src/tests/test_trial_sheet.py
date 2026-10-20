"""The trial file Sriram sees has 20 cases, a blank label column and NO generator labels."""
import csv
from pathlib import Path

TRIAL = Path(__file__).resolve().parents[1] / "data" / "stage0_trial"


def test_twenty_cases_and_blank_sheet():
    rows = list(csv.DictReader((TRIAL / "label_sheet.csv").open()))
    assert len(rows) == 20
    for r in rows:
        assert all(v == "" for k, v in r.items() if k != "case_id")


def test_markdown_has_no_generator_labels(trial):
    md = (TRIAL / "trial_cases.md").read_text()
    assert md.count("\n## TRIAL-") == 20
    for forbidden in ("scenario", "gold", "edge_tags", "adversarial_tags", "evidence_basis",
                      "suspicious_expected", "fraud_disguised", "ph_modify", "ph_verify", "CONTRADICTED =>"):
        assert forbidden not in md, forbidden
    scen_ids = {l["scenario"] for l in trial["labels"] if "_" in l["scenario"]}
    for sid in scen_ids:  # internal scenario identifiers (e.g. ph_claim_unresolved) must not leak
        assert sid not in md, sid


def test_trial_mix_covers_outcomes(trial):
    outs = {l["gold"]["outcome"] for l in trial["labels"]}
    assert {"VERIFIED_AS_REPORTED", "MODIFY", "ESCALATED", "OUT_OF_SCOPE"} <= outs


def test_hidden_labels_not_in_trial_folder():
    assert not any("label" in f.name and f.suffix == ".jsonl" for f in TRIAL.iterdir())
    assert (TRIAL.parent / "stage0_trial_HIDDEN_generator_labels" / "labels.jsonl").exists()
