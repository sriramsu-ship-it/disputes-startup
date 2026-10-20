# ADR-002: Queue — Postgres job table with SELECT ... FOR UPDATE SKIP LOCKED

**Date:** 2026-10-20  **Status:** Proposed  **Author:** developer

## Context
Cases move through asynchronous steps (classify, investigate, draft) with up to 4 LLM calls per case, a 90s case budget (R-15) and concurrency of about 10 for the T3 run (R-28). Volumes in the MVP are tiny (≈1,100 synthetic cases per eval run). Every state change must be audited (R-21) in the same transaction as the work.

## Decision
A `jobs` table in the same Postgres database, claimed with `SELECT ... FOR UPDATE SKIP LOCKED`, with `attempts`, `run_after` (backoff), `locked_until` (lease) and a dead-letter state that escalates the case (fail safe). Job completion, the case state change and the audit event commit in one transaction. No message broker.

## Options considered
| Option | Pros | Cons | Cost to reverse |
|---|---|---|---|
| **Postgres SKIP LOCKED table** | No new infra; transactional with the audit write; easy to test | Not for very high throughput | Low (workers call a small interface) |
| Redis/RQ or Celery | Mature | New stateful component; job and audit not in one transaction | Medium |
| SQS / cloud queue | Managed | Cloud lock-in; at-least-once delivery needs idempotency anyway; no local parity | Medium |

## Consequences
Easier: exactly-once state transitions per transaction, local testing. Harder: very high fan-out (not needed). Monitor: queue depth and stuck leases; a reaper returns expired leases.

## Compliance and security impact
Because a job's effect and its audit event commit together, no state change can occur without its audit record, and a crash cannot leave a half-written decision. A job that exhausts retries escalates the case instead of dropping it (N1, N6).

## Revisit trigger
Sustained queue latency above 5s at pilot volume, or a pilot deployment that mandates a managed queue.
