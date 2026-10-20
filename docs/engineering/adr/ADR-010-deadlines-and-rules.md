# ADR-010: Deadlines and rules — versioned code plus reference tables as data with `verified` and `source`

**Date:** 2026-10-20  **Status:** Proposed (table format built in Stage 0; clock and rules in Stage 1)  **Author:** developer

## Context
R-05: store the CRA-provided due date; internal target = due date − 3 business days (config); AT_RISK from 2 business days before the target until the due date ends; BREACHED after; business days exclude weekends and a holiday table; end of day in a configured zone. No statutory deadline computed from memory. R-09: DPD → expected rating via a versioned table. R-10: deterministic outcome rules with precedence. R-35: every table carries `verified` and `source`. The calendar and zone are unverified (U21); codes and rating values are unverified (U6).

## Decision
1. **Rules in plain, versioned Python** (no rules engine), each with a stable rule ID and version logged on every evaluation (R-29). The VERIFY invariant is proven by ≥10,000 property tests (B1).
2. **Reference tables as JSON data**, one file per table: `table_id`, `table_version` (semver), `verified`, `synthetic_placeholder`, `source`, `source_note`, `entries`. Changes are ADMIN events (R-21). Stage 0 tables: `dispute_code_map` (invented `PLH-*` codes), `payment_rating_map` (invented `PH_*` labels; DPD buckets unverified), `holiday_calendar` (5 USC 6103(a) list for 2026-2027 with the 6103(b) Saturday→Friday rule; **Sunday→Monday is an assumption**, not stated in 6103(b)), `time_zone` (America/New_York placeholder). All `verified=false`, test-enforced.
3. **The clock never derives a statutory window.** It only uses the CRA's due date. Synthetic fixtures use due dates 10-20 business days after intake, explicitly not a statement of the real ACDV window.
4. **Day-granularity in Stage 0.** The fixture helper (`synthgen/bizdays.py`) evaluates on dates only; the Stage 1 clock adds end-of-day in the configured zone. The Stage 0 helper is test-data tooling, not the production clock.

## Options considered
| Option | Pros | Cons | Cost to reverse |
|---|---|---|---|
| **Code + tables as data with verification flags (proposed)** | Deterministic, reviewable diffs, R-35 gate is trivial | Need discipline on versioning | Low |
| Rules engine product (Drools-type, DMN) | Business-editable | Heavy dependency; harder to property-test; ADR-worthy infra | High |
| Constants in code | Simplest | No `verified`/`source`; changes not auditable as data | Medium |

## Consequences
A wrong placeholder table produces consistently wrong but internally consistent results, and evals cannot catch it (circular). That is why non-synthetic mode is blocked until each table is verified from a partner's developer guide or the CDIA CRRG (U6) and counsel (U21).

## Compliance and security impact
Every outcome is traceable to rule ID/version and table versions with their `verified` status (R-22 export). Deadline logic is deterministic and tested, never model-driven.

## Revisit trigger
Any table becomes verifiable (partner guide, CRRG); counsel or a partner names the business-day calendar or zone (U21); a rule change request from Phase 2 practitioners.
