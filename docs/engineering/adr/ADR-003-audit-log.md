# ADR-003: Audit log — insert-only, hash-chained events with an external anchor (design only)

**Date:** 2026-10-20  **Status:** Proposed (design only; built in Stage 1)  **Author:** developer

## Context
"Why did we respond this way" must be reconstructable months later (N4, U3). R-21 requires an event for every state change, rule evaluation, model call, human action, config/reference-table change and AUDITOR/ADMIN read; insert-only for the app role; per-case plus global hash chains with serialised writes; an anchor to object-locked storage at least every 15 min; and a `verify` command. R-23 sets configurable retention (7-year placeholder, no delete path). R-32 needs daily backup and a restore drill where `verify` passes.

## Decision
1. **Table `audit_events`** (append-only): `event_id` (bigserial), `tenant_id` (ADR-008), `case_id` (nullable for ADMIN/config events), `event_type`, `actor_type` (SYSTEM/MODEL/HUMAN), `actor_id`, `actor_role`, `occurred_at` (UTC, from the DB clock), `payload` (canonical JSON: inputs with hashes, rule ID/version, model ID, prompt-template hash, reference-table versions and `verified` flags, output, confidence, reason code/text), `payload_sha256`, `case_prev_hash`, `case_hash`, `global_prev_hash`, `global_hash`, `schema_version`.
2. **Hashing:** `case_hash = SHA-256(case_prev_hash ‖ canonical(event without hash fields))`; the global chain does the same over all events. Canonical JSON = sorted keys, no whitespace, UTF-8, timestamps as RFC 3339 UTC.
3. **Serialisation:** inserts take `pg_advisory_xact_lock` on a global key, so chain heads are read and written in one serial transaction (MVP volumes make this cheap).
4. **Insert-only:** the app role has INSERT and SELECT only; a trigger rejects UPDATE/DELETE for every role except the migration owner, and the trigger itself is audited by `verify` (it checks that the trigger exists).
5. **Anchor:** every 15 min (config) a job writes `{global_head_event_id, global_hash, at}` to an object-locked bucket (compliance mode, retention ≥ audit retention). `verify` recomputes both chains, reports the first broken `event_id`, and compares with the latest anchor (detects a full rewrite by a DB superuser).
6. **Reads:** AUDITOR/ADMIN case reads write a `CASE_READ` event (R-21).
7. **Retention:** no delete path in the MVP (R-23). Counsel flag: may conflict with future privacy-deletion duties (U10).

## Options considered
| Option | Pros | Cons | Cost to reverse |
|---|---|---|---|
| **Postgres hash chain + object-lock anchor** | Boring; verifiable by our own code; transactional with state changes | We own the verification code | Medium |
| Managed ledger DB (e.g., QLDB-type) | Built-in digests | Service availability/lock-in risk; not transactional with case data | High |
| Append-only log files in WORM storage only | Simple tamper evidence | Hard to query for exports; two-phase write with the DB | Medium |
| Signed events (per-event signatures, KMS) | Non-repudiation per event | Key management; adds little over anchoring for the MVP | Low (can add later) |

## Consequences
Easier: per-case export with chain status (R-22); proving tampering. Harder: schema evolution of `payload` (versioned with `schema_version`); global serialisation limits write throughput (fine for MVP). Monitor: anchor job failures (alert), `verify` run nightly.

## Compliance and security impact
This is the core of the defensibility story. Tamper evidence holds against the app role (grants), against row edits (chain), and against a full rewrite (anchor). It does **not** prevent a superuser from deleting the database; backups (R-32) and the anchor bound that. The store holds unmasked PII (R-27), so it is encrypted at rest and access is role-restricted and itself audited (ADR-009). Whether an examiner or court accepts this record is unknown (U3; counsel and Phase 2 G4).

## Revisit trigger
Counsel sets retention or deletion duties (U10); a design partner's records policy requires a specific WORM system; write throughput needs exceed serialised inserts.
