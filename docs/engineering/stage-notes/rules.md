# Stage notes: rules module (R-08, R-09, R-10, R-29, R-35, Appendix B T0/B1)

**Date:** 2026-11-07  **Branch:** `agent/rules`  **Author:** developer (rules agent)
**Status:** built and tested on synthetic data only. Reference tables are `verified=false` placeholders, so every result here is internally consistent but not validated against Metro 2 (U6).

## What was built
| Path | Requirement | What it does |
|---|---|---|
| `src/disputes/rules/gate.py` | R-35 (ADR-010 §2, ADR-013 intent) | `check_tables(cfg, tables=None)`: checks that every table has a boolean `verified`, a non-empty `source` and a `table_id` that matches its file name (`MalformedTable` if not). Raises `UnverifiedTables` in `mode="live"` while any table is `verified=false`. An unknown mode string raises `ValueError`, so a typo cannot fall through to either mode. Returns `reference.versions()`. |
| `src/disputes/rules/evidence.py` | R-08 | `disputed_months` returns the ACDV months ∪ the claim months, sorted. `gather_evidence` builds the evidence list with exactly the docstring ID scheme. Also exposes the helpers `window_months`, `shift_month`, `valid_month` and `make_evidence`. |
| `src/disputes/rules/compare.py` | R-09 | `compare_months` maps DPD to the expected rating through the `payment_rating_map` table and returns MATCH, MISMATCH or NO_DATA per month, citing `EV-CYCLE-<m>`. Also exposes `expected_rating`. |
| `src/disputes/rules/outcome.py` | R-10, R-29 | `decide` applies full precedence, records every reason as a `RuleFiring`, adds one `R-10.OUTCOME` firing per decision, and never returns DELETE. The rule list is in the module docstring. |

### Evidence conventions (the agents module cites these)
- **IDs:** `EV-ACDV`, `EV-ATT-<attachment_id>`, `EV-ACCOUNT`, `EV-PROFILE`, `EV-CYCLE-YYYY-MM`, `EV-NOTE-<n>`, `EV-FTNOTE-<n>`.
- **`<n>` in note IDs** is the 1-based position in the SoR `notes` or `free_text_notes` list. The SoR's own `note_id` (for example `N1`) is kept in the content.
- **Ledger:** the scheme has no ledger ID. Each `EV-CYCLE-<m>` holds the cycle row plus `ledger_transactions`, the transactions posted in that calendar month.
- **Window:** the union of [m−2, m+2] over the disputed months, not the min..max span, limited to cycles that exist.
- **Duplicate cycle rows for one month:** the content becomes `{cycle_month, conflicting_rows: [...]}`. The comparison returns NO_DATA, which gives EVIDENCE_MISSING, and R-10 also raises EVIDENCE_CONFLICT.
- **`EV-ACCOUNT`** leaves out `cycles`, `notes`, `transactions` and the consumer's `ssn` and `dob` (minimisation, ADR-009).
- **`EV-PROFILE`** is the full reported profile: one `{cycle_month, reported_rating}` per cycle.
- **`EV-ATT-*`** holds the extracted text and metadata, which the agents need for quote location.
- **Kinds:** `acdv`, `attachment`, `account`, `profile`, `cycle`, `note`, `free_text_note`. Sources: `acdv` and `mock_sor`.
- **Hashing:** SHA-256 over `disputes.audit.chain.canonical(content)`, with `retrieved_at = now`.
- **Missing account:** only `EV-ACDV` and the `EV-ATT-*` items are returned. Every month then compares as NO_DATA, giving EVIDENCE_MISSING.
- **Malformed month strings** (for example "March 2026") are kept as disputed months, so they fail safe to NO_DATA, but they do not widen the window.

### R-10 rule set (RULES_VERSION 1.0.0)
Every rule below is evaluated; nothing short-circuits the record.

| Step | Rule | Effect |
|---|---|---|
| U | Upstream reasons | `upstream_escalations` ∪ `classification.escalations` are recorded with rule ID `<origin req>.<REASON>`, for example `R-05.BREACHED`. |
| S | Scope guard | A route of ESCALATE_* adds its reason. IDENTITY_FRAUD in the categories adds ID_FRAUD_SUSPECTED. More than one real category adds MULTI_ISSUE. UNCERTAIN or an empty set adds CLASS_CONFLICT. A route that contradicts the categories adds CLASS_CONFLICT (fail safe): INVESTIGATE without exactly {PAYMENT_HISTORY}, or OUT_OF_SCOPE with exactly {PAYMENT_HISTORY}. |
| S | Out of scope | A single non-PH category routed OUT_OF_SCOPE with no escalation gives outcome OUT_OF_SCOPE. |
| | Gate on month rules | The month and note rules run only when the categories are exactly {PAYMENT_HISTORY}. Otherwise the comparisons are recorded as a NOTE firing. |
| M1 | No comparisons | MONTHS_UNDETERMINED (`R-08.MONTHS_UNDETERMINED`). |
| M2 | Any NO_DATA | EVIDENCE_MISSING. |
| C1 | `conflicting_rows` in a disputed cycle | EVIDENCE_CONFLICT. |
| C2 | Conflict note overlaps a disputed month | EVIDENCE_CONFLICT for a HARDSHIP, DEFERRAL or FORBEARANCE note (overlap definition below). |
| C3 | `llm_note_flag` | EVIDENCE_CONFLICT, citing the `EV-FTNOTE-*` items. |
| K1 | Claims, only when otherwise VERIFY | Any claim not *validly* CONTRADICTED gives CLAIM_UNRESOLVED. "Validly" means the finding is CONTRADICTED and the claim cites at least one evidence ID, all of which exist. A finding of None counts as unresolved. If the case is already escalated or MODIFY, a NOTE firing `R-10.CLAIM_NOT_CONTRADICTED` is recorded instead, so the reviewer still sees it. |
| O | Outcome | Any reason gives ESCALATED with no corrections. When escalated in scope, a `R-09.MISMATCH` NOTE firing is added for each mismatched month ("mismatch shown, no outcome proposed"). Otherwise any MISMATCH gives MODIFY with one `Correction(month, "payment_rating", reported, expected)` per mismatched month. Otherwise the outcome is VERIFIED_AS_REPORTED. |

- `table_versions = reference.versions("payment_rating_map")`.
- Firing evidence IDs are filtered to IDs that exist in the evidence list.
- `R-10.OUTCOME` always cites at least one ID when `EV-ACDV` is present.
- DELETE is unreachable. An explicit `raise` guards it and still works under `python -O`.

**Note overlap (C2):** the closed date interval `[start_date, end_date]` intersects the disputed **calendar** month `[first day, last day]`.
- A missing `end_date` means the note is open-ended.
- These are treated as overlapping (fail safe): a missing or unparseable start date, an unparseable end date, or an end date before the start date.
- An unknown note type (not in the `NoteType` enum) is treated as a conflict type (fail safe).
- PRIOR_DISPUTE and OTHER never conflict.

## Tests: command and actual result
`cd src && /home/claude/disputes-startup/.venv/bin/python -m pytest -q`
**Result: `139 passed in 53.89s`.** That is the 76 existing tests plus 63 new ones, run 2026-11-07 against local Postgres 16.

| File | Tests | Covers |
|---|---|---|
| `src/tests/test_rules_units.py` | 58 | R-35 gate (synthetic, live refusal, live pass, malformed tables, unknown mode). R-08 months, window, IDs, hashes, minimisation, missing account, real fixture record. R-09 buckets and MATCH/MISMATCH/NO_DATA. Every PRD §6 R-08/R-09/R-10 acceptance criterion. Overlap edge cases, fail-safe notes, the LLM flag, scope guard (10 category/route combinations), upstream reasons, all-reasons-recorded. |
| `src/tests/test_rules_properties.py` | 3 | T0/B1 (see below). |
| `src/tests/test_rules_fixture_agreement.py` | 2 | Agreement with the 200 fixture labels, and a check of the filter. |

### T0 / B1 property tests: 0 counterexamples
- `test_b1_invariants_near_verify_inputs`: **10,000** examples.
  - Inputs are clean VERIFY cases with random single perturbations (month result, notes, duplicate cycle rows, claim finding and citation, categories, route, upstream reasons, LLM flag).
  - Outcomes in the run reported here: VERIFIED_AS_REPORTED 2,446, MODIFY 396, ESCALATED 7,153, OUT_OF_SCOPE 5.
  - The test asserts at least 1,000 VERIFY outcomes, so the VERIFY invariant is not tested vacuously.
- `test_b1_invariants_arbitrary_inputs`: **5,000** examples.
  - Inputs are fully arbitrary: any categories and route, malformed months, broken notes, unknown evidence IDs, findings of None, any upstream reasons.
  - Almost all of these escalate, as they should.
- **Every invariant is checked on all 15,000 inputs:**
  - never DELETE;
  - VERIFY ⇒ at least 1 month, all MATCH, no reasons, no upstream reasons, no LLM flag, every claim CONTRADICTED with valid citations, categories == {PH}, route INVESTIGATE, no overlapping conflict note (checked by an independent day-enumeration implementation), no conflicting cycle rows;
  - escalation precedence:
    - upstream reasons ⊆ recorded reasons;
    - ESCALATED ⇔ reasons ≠ ∅;
    - ESCALATED ⇒ no corrections;
    - NO_DATA ⇒ EVIDENCE_MISSING;
    - no months ⇒ MONTHS_UNDETERMINED;
    - a conflict note or the LLM flag ⇒ EVIDENCE_CONFLICT;
    - in scope with no reasons and a MISMATCH ⇒ MODIFY;
  - MODIFY ⇒ exactly one correction per mismatched month;
  - R-29: every reason has a firing with a rule ID and RULES_VERSION, and there is exactly one `R-10.OUTCOME` firing;
  - every cited ID exists;
  - `decide` is deterministic.
- `test_r09_compare_property`: 2,000 examples against an independent DPD-bucket reference.
- **Runtime:** about 23 s (near-verify) + 16 s (arbitrary) + 3.4 s (R-09), about 43 s of the 54 s suite on a shared 2-CPU box. `deadline=None`, `database=None`.
- **Mutation check (run by hand, then reverted):**
  - Mutant 1 dropped NOT_ADDRESSABLE from the CLAIM_UNRESOLVED check.
  - Mutant 2 required at least 2 NO_DATA months before raising EVIDENCE_MISSING.
  - The near-verify property test failed on both, so it catches real rule bugs.

### Fixture agreement (rules in isolation): **148 / 148 cases agree, 0 disagreements**
Fields compared per case: disputed months, per-month results, outcome, the set of escalation reasons, and corrections.

**Filter (defined on inputs, not on the gold outcome).** A case is included only if all of these hold:
- `duplicate_of` is null;
- gold is not INTAKE_INVALID;
- `categories == dispute_code_categories == ["PAYMENT_HISTORY"]`.

This excludes 52 cases that R-02 or R-07 decide before evidence is gathered: 10 ID fraud, 20 out of scope (14 balance, 6 other), 6 multi-issue, 4 class conflict, 8 malformed, 4 duplicates.

**Inputs fed to the rules:**
- the gold claims, with `evidence_basis` mapped to our IDs;
- classification {PH}/INVESTIGATE;
- upstream reasons = the gold reasons ∩ {BREACHED, DOC_UNREADABLE}. Both are intake outputs, and the oracle keeps evaluating the rules after them.

**Agreement by scenario (all agree):**
- verify scenarios: ph_verify 54, ph_verify_note_near_miss 6;
- outcome-changing scenarios: ph_modify 24, ph_evidence_conflict 10, ph_claim_unresolved 10, ph_evidence_missing 8, ph_claim_month_extends 6, ph_months_undetermined 4;
- intake-flagged scenarios: doc_unreadable 4, missing_document 4, deadline_breached 4, deadline_at_risk 4, deadline_on_holiday 2;
- adversarial scenarios: pii_bait 4, imperative_control 4.

**This is a consistency check, not independent evidence (U35).** `synthgen/oracle.py` encodes the same PRD rules, and I read its `note_overlaps` and `derive_gold` to understand the intended semantics (nothing is imported). Agreement shows that two implementations of one reading of the PRD match on 148 generator-intent cases. It does not show that the reading is right, or that the rules hold on real disputes.

## What is stubbed or faked
- `payment_rating_map` uses invented `PH_*` labels and unverified DPD buckets (`verified=false`).
- The SoR is the fixture-backed `MockSystemOfRecord`, and DPD is supplied rather than derived (PRD R-09).
- `llm_note_flag` is only an input. The agents module or the pipeline must produce it.

## Known limits and PRD ambiguities (for the PM)
1. **Overlap uses calendar months, not billing-cycle periods.** A DEFERRAL ending 3 March, with a cycle date of 25 March, overlaps "2026-03" under this rule, even though it ends before the cycle date. The oracle makes the same choice. Ask the PM or practitioners (U20) whether overlap should be measured against the cycle period (previous cycle date + 1 to cycle date).
2. **CLAIM_UNRESOLVED only when the case would otherwise VERIFY.** The PRD's "all triggered reasons are recorded" conflicts with "→ CLAIM_UNRESOLVED **instead**" (of VERIFY). I followed the stub and the oracle: the reason is raised only when the case would otherwise VERIFY. In other cases a NOTE firing records the unresolved claims.
3. **MODIFY can be proposed while a claim is SUPPORTED or NOT_ADDRESSABLE.** This follows the PRD literally. Example: the consumer says they paid on time in March, and the mismatch is in May. The NOTE firing makes this visible, but the PM should confirm that MODIFY should not escalate when a claim about a non-mismatched month is unresolved.
4. **Zero claims and all MATCH gives VERIFY** ("every claim CONTRADICTED" is vacuously true). Missed claims must be caught upstream (R-11 UNADDRESSED_CLAIM, B10). Consider requiring at least 1 claim for VERIFY.
5. **Deliberately stricter than the PRD:** a CONTRADICTED claim with no cited evidence, or with an unknown ID, counts as unresolved. Unknown note types and unreadable note dates fail safe to EVIDENCE_CONFLICT. Duplicate SoR cycle rows give EVIDENCE_MISSING + EVIDENCE_CONFLICT.
6. **The window is the union of ±2-month windows,** not the min..max span. The PRD says "disputed months ±2 months", which allows either reading.
7. **Inconsistent classification input escalates instead of trusting it:** route and categories that disagree give CLASS_CONFLICT.

## Contract-change requests (for the integrator)
1. **`src/disputes/contracts_bridge.py` must re-export `SystemOfRecord`.** The original `evidence.py` stub imports it from there, but it is not exported. Importing the stub as written raises `ImportError`. I worked around this locally with `from disputes_core.contracts import SystemOfRecord`. Proposed diff:
   ```diff
    from disputes_core.contracts import (  # noqa: F401
        AcdvSource, Attachment, Dispute, FixtureAcdvSource, LlmClient, MockSystemOfRecord,
   -    ResponseSink, StubResponseSink, acdv_to_dispute, canonical_json,
   +    ResponseSink, StubResponseSink, SystemOfRecord, acdv_to_dispute, canonical_json,
    )
   ```
2. **Comment fix in `domain.py`, `Evidence.kind`.** The comment lists `"ledger"`, but no ledger item exists (the ledger is inside each cycle). There is a `"profile"` kind instead. Proposed diff:
   ```diff
   -    kind: str                  # "account" | "cycle" | "ledger" | "note" | "free_text_note" | "attachment" | "acdv"
   +    kind: str                  # "account" | "cycle" (incl. ledger_transactions) | "profile" | "note" | "free_text_note" | "attachment" | "acdv"
   ```
3. **Additive signature change:** `gate.check_tables(cfg, tables=None)` gained an optional `tables` parameter for tests. Existing callers are unaffected.

## What the integrator needs to wire up
- **`Deps`:** `disputed_months=rules.evidence.disputed_months`, `gather_evidence=rules.evidence.gather_evidence`, `compare_months=rules.compare.compare_months`, `decide=rules.outcome.decide`.
- **Start-up (CLI/web/worker):** call `rules.gate.check_tables(cfg)` once. Refuse to start on `UnverifiedTables`, `MalformedTable` or `ValueError`. Write the returned versions into the start-up audit event.
- **Calling `decide`:**
  - Call `decide` even when there are no months: pass `comparisons=[]` and `decide` raises MONTHS_UNDETERMINED itself with a firing.
  - Pass every upstream reason in `upstream_escalations`: intake BREACHED and DOC_UNREADABLE, the claims step's QUOTE_UNLOCATED and UNADDRESSED_CLAIM, and LLM_UNAVAILABLE. Classification escalations are read from `classification.escalations`.
- **DRAFT_INVALID:** it arises after `decide`. Re-run `decide` with it added to `upstream_escalations`, so the stored Decision has the firing (R-29), rather than appending the reason by hand.
- **Persistence:** store `Decision.firings`, `rules_version` and `table_versions` in the DECISION artifact and the audit payload (R-21, R-22). Store the evidence list, with hashes, as the EVIDENCE artifact.

## Self-review
- **Acceptance criteria:** every one has a test that I ran.
- **Decision logging:** each decision carries its inputs (evidence IDs and hashes), versions (rules and table) and outputs. Persisting the Decision artifact and its audit event is the pipeline's job (platform-core).
- **Fail-safe paths:** missing account, malformed months, broken notes, duplicate rows, unknown citations and inconsistent classification all escalate.
- **No DELETE path exists.**
- **No network calls; no imports from synthgen.** The fixture agreement test reads only fixture and label files.
- **PII:** `EV-ACCOUNT` leaves out SSN and DOB. Attachment text is included because R-11 needs it; it is untrusted data for the agents (R-14).
- **Confidence:** high that the code matches this reading of the PRD (unit tests, 15k property inputs, two mutants killed, 148/148 agreement). Confidence in the reading itself is medium. Items 1-4 above could change outcomes on real disputes, and the rating table is unverified.
