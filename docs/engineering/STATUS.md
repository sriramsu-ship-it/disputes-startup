# Engineering Status

**Last updated:** 2026-10-20 by developer (Stage 0 complete, awaiting Sriram's gate review)

## Built (Stage 0, all on synthetic data)
| Item | Path | Evidence it works |
|---|---|---|
| ADR-001 to ADR-010 (all **Proposed**) | `docs/engineering/adr/` | Docs only; not tested. ADR-006 needs Sriram's decision (Q13) |
| Synthetic generator v0 (seeded, stdlib only) | `src/synthgen/` | 67 tests pass (below) |
| Placeholder reference tables, R-35 format, all `verified=false` | `src/synthgen/reference_tables/` | `test_reference_tables_format_and_unverified` |
| JSON Schemas with `synthetic: const true` | `src/synthgen/schemas/` | `test_schema.py` |
| ADR-004 contract skeleton (`Dispute`, `FixtureAcdvSource`, `MockSystemOfRecord`, `StubResponseSink`) | `src/disputes_core/contracts.py` | `test_contracts.py` (8 tests) |
| R-34 eval-isolation check (prompt library is empty in Stage 0) | `src/synthgen/isolation.py`, `src/prompts/` | `test_isolation.py`, including a planted-contamination test |
| Committed fixture set: 200 cases, seed 20261019 | `src/data/fixtures/seed20261019_n200/` | `test_committed_fixture_matches_regeneration` (file hashes match a fresh run) |
| 20-case labelling trial for Sriram | `src/data/stage0_trial/trial_cases.md`, `label_sheet.csv` | `test_trial_sheet.py` (no generator labels leak into his file) |

**Test run (2026-10-20, Python 3.13.16, `cd src && ../.venv/bin/python -m pytest`): 67 passed, 0 failed, 0 skipped, about 4.7s.** The suite covers:
- determinism: same seed gives byte-identical files; a hypothesis property over 15 seeds; identical across `PYTHONHASHSEED` 0, 1 and 12345 (run by hand);
- schema validity of every record;
- `synthetic=true` on every record and sub-record;
- label consistency: claim spans locate quotes exactly; month results recomputed from the SoR; the VERIFY invariant holds on gold; no DELETE; MODIFY corrections match the table; repeat and duplicate linkage; twins differ only by the injection; deadline tags match the clock;
- R-26 shares: edge ≥15% and adversarial ≥10% at n = 100, 200 and 1,000;
- every required edge and adversarial tag is present;
- PII scan: no real-looking SSN or Luhn-valid card number;
- contract tests;
- R-34;
- the T1-strata feasibility probe.

**Fixture set n=200 (seed 20261019):** edge cases 31%, adversarial 11%.
- Outcomes: 74 VERIFIED, 30 MODIFY, 72 ESCALATED, 20 OUT_OF_SCOPE, 4 DUPLICATE_IGNORED.
- Escalation reasons seen: all 10 that do not need an LLM. QUOTE_UNLOCATED, UNADDRESSED_CLAIM, DRAFT_INVALID and LLM_UNAVAILABLE need the Stage 2 LLM path and cannot be produced by data alone.
- 247 labelled claims.

## Stubbed / faked (stated plainly)
- **ACDV fixture shape is our own placeholder** (`placeholder-acdv-0.1.0`). It is not the e-OSCAR schema (U6). The dispute codes (`PLH-*`) and rating labels (`PH_*`) are invented, and so are the DPD bucket boundaries.
- **Holiday table:** the 5 USC 6103(a) list for 2026-2027 only. The rule that moves a Sunday holiday to Monday is an assumption. Whether CRAs use this calendar is unverified (U21).
- **Due dates in fixtures are synthetic** (10-20 business days after intake), not real ACDV windows.
- **The mock SoR supplies DPD per cycle** (R-09). Transactions are illustrative and are not used to derive DPD.
- **Gold labels are generator intent.** They come from `synthgen/oracle.py`, which encodes the PRD rules, so they are circular for rule logic. They are T1-style labels and must not be used as T3 gold. Production code is test-blocked from importing the oracle.
- `synthgen/bizdays.py` is a fixture helper that works at day granularity. It is **not** the R-05 clock (Stage 1).
- **No CI is configured** (no remote repo). The tests run locally only.

## Not built (later stages, not approved)
Database, audit chain and `verify`, intake validation (R-02), the R-05 clock, rules (R-09/R-10), authN/RBAC, LLM client and any LLM call, the UI, export and the eval harness. ADR-011, 012 and 013 are not written (Stage 1). ADR-010 already defines the R-35 table format that ADR-013 will gate.

## Known v0 limits (affect Stage 2 and Stage 4, not Stage 0)
- Letters are assembled from template sentences, so linguistic variety is low. They are not realistic enough for T3 or LLM evals (U20).
- Each injection surface has one string, and there are three fraud phrasings. T2 needs ≥20 variants per surface, and the ≥150-case T1 fraud stratum needs many more distinct phrasings (U34).

## Broken
Nothing known.

## Next (only after Sriram approves Stage 1 in HANDOFFS.md)
Stage 1 per PRD §12: ADR-011, 012, 013; Postgres schema; the audit chain, anchor and `verify`; intake, clock, dedup and repeat; the state machine; the mock SoR adapter; comparison and outcome rules with ≥10,000 property tests (B1); the reference-table gate; and CI.
