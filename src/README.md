# src/ — Stage 0: synthetic data generator and fixtures

**Everything here is SYNTHETIC.** No real person, company, account or bureau data. The ACDV fixture
shape (`fixture_schema_version = placeholder-acdv-0.1.0`) and every code and rating table are
**placeholders** (`verified=false`). They are **not** the e-OSCAR schema, code list or Metro 2 values (U6).

## What is here
| Path | What |
|---|---|
| `synthgen/generator.py` | Seeded generator: ACDV fixtures, mock system-of-record accounts (DPD per cycle, reported rating, illustrative transactions, structured and free-text notes), text-native consumer letters, claim-level labels, edge and adversarial cases |
| `synthgen/oracle.py` | Generator-intent gold labels (PRD v1.1 rules). **T1-style labels only; never T3 gold.** Production code may not import it (test-enforced) |
| `synthgen/reference_tables/*.json` | Placeholder tables in R-35 format (`table_version`, `verified=false`, `source`, `source_note`): dispute-code map, rating map, holiday calendar (5 USC 6103 list, 2026-2027), time zone |
| `synthgen/schemas/*.schema.json` | JSON Schemas (draft 2020-12). `synthetic` is `const: true` in every record type |
| `synthgen/pii_guard.py` | Detector for real-looking SSNs (SSA never-assigned rules) and Luhn-valid card numbers |
| `synthgen/isolation.py` | R-34 check: eval-case text hashes must not appear in `src/prompts/` |
| `disputes_core/contracts.py` | ADR-004 canonical `Dispute` and adapter protocols; `FixtureAcdvSource`, `MockSystemOfRecord`, `StubResponseSink`. No intake validation (Stage 1) |
| `data/fixtures/seed20261019_n200/` | Committed 200-case fixture set + `manifest.json` (counts, file hashes, table versions) |
| `data/stage0_trial/` | **Sriram's 20-case labelling trial**: `trial_cases.md` (read this), `label_sheet.csv` (fill this) |
| `data/stage0_trial_HIDDEN_generator_labels/` | Generator labels for the trial. Do not open until labelling is done |
| `tests/` | 67 tests (pytest + hypothesis + jsonschema) |

## Run
```bash
cd /home/claude/disputes-startup
python3 -m venv .venv && .venv/bin/pip install -r src/requirements-dev.txt
cd src
../.venv/bin/python -m pytest                     # all tests
../.venv/bin/python -m synthgen.cli generate --seed 20261019 --n 200 --out data/fixtures/seed20261019_n200
../.venv/bin/python -m synthgen.cli trial --out data/stage0_trial
```
The generator uses only the standard library. Test dependencies are pinned in `requirements-dev.txt`.
Same seed gives byte-identical files (tested). `n` must be at least 100.

## Labels and tags
Each case has a label record: `categories`, `claims` (verbatim quote, code-located span, type, months,
finding, evidence basis), `gold` (outcome, escalation reasons, month results, corrections),
`suspicious_expected` (NONE/LOW/HIGH), `edge_tags`, `adversarial_tags`, `twin_group` (injection case plus its clean twin),
`repeat_of` and `duplicate_of`. The generator cross-checks every case against its scenario's declared
intent and raises `IntentMismatch` rather than emitting an inconsistent label.

Edge tags: missing_document, missing_records, conflicting_records, deferral_or_hardship, repeat,
duplicate, malformed_input, multi_issue, near_deadline, deadline_breached, deadline_on_holiday,
doc_unreadable, months_undetermined. Adversarial tags: injection_letter_body, injection_hidden_text,
injection_acdv_free_text, injection_file_metadata, injection_tool_syntax, pii_bait, identity_fraud_disguised.

## How the data is made obviously synthetic
Invented surnames (Synthwood, Fixturo...), state `ZZ`, ZIP `000xx`, phone area code `000`, CRAs `SYNTH-CRA-n`,
furnisher "Example Fintech Lender (SYNTHETIC)", accounts `SYNACCT##########`, codes `PLH-*`, ratings `PH_*`.
SSN-shaped values use area 900-999 **and** group 00, which SSA never assigns. PII-bait card numbers fail the Luhn check.

## Known limits (v0)
- Letters are template sentences: low linguistic variety. Not realistic enough for T3 or for an LLM eval (generator v1, Stage 2).
- One injection string per surface and three fraud phrasings. T2 needs at least 20 per surface (Stage 2).
- Due dates are synthetic (10-20 business days after intake); they are not real ACDV response windows.
- The oracle shares the PRD rules with the future R-10 code, so gold labels are circular for rules; B8 and T3 address this.
