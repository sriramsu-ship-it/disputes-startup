# ADR-008: Tenancy — DEFERRED; single tenant with a reserved `tenant_id`

**Date:** 2026-10-20  **Status:** Superseded in part 2026-11-07 (see Revision below); original: Proposed (recorded as deferred, per PRD v1.1 §9)  **Author:** developer

## Context
Multi-tenancy is a non-goal for the MVP (PRD §3). Appendix A Q2 plans a dedicated single-tenant deployment per pilot customer. Retrofitting a tenant key into an audit chain and every query later is costly; adding the column now is cheap.

## Decision
Build single tenant. Every persisted table (cases, evidence, audit events, jobs, config) carries a non-null `tenant_id`; the MVP uses one constant (`synthetic-tenant-0`, already in Stage 0 fixtures and the canonical `Dispute`). No row-level security, tenant routing or tenant admin in Phase 1. Each pilot gets its own deployment and database.

## Options considered
| Option | Pros | Cons | Cost to reverse |
|---|---|---|---|
| **Single tenant + reserved column (deferred)** | Near-zero cost; no false isolation claims; easy path to either model | No shared SaaS economics yet | Low |
| Shared DB with Postgres RLS now | SaaS-ready | Isolation code nobody needs yet; must be tested to bank standard | Medium |
| Nothing reserved | Simplest | Expensive migration of audit chain later | High |

## Consequences
We must not describe the prototype as multi-tenant. Monitor: any query written without `tenant_id` (a Stage 1 lint/test).

## Compliance and security impact
Per-customer deployment is the strongest isolation for the first pilots and simplest for vendor risk. `tenant_id` is included in audit-event hashes so a later move to shared infrastructure keeps chains attributable.

## Revisit trigger
A second paying pilot, or a buyer requiring shared SaaS pricing (then write ADR for RLS and per-tenant keys).

## Revision 2026-11-07: multi-tenant shared platform (managed-service pivot)
**Trigger met:** Sriram decided we run disputes for several furnisher clients ourselves (DECISIONS 2026-11-07), so one deployment holds several clients' cases.

**Decision now:** one shared database; every tenant-owned row has `tenant_id`; tenant scoping is enforced in the application (every repository query takes and filters by `tenant_id`, test-enforced); client users (`CLIENT_VIEWER`) are bound to exactly one tenant; our staff reach a tenant only through `staff_tenant_access`. The `ops` tenant holds platform-wide config. `tenant_id` stays in the audit hash body.

**Required before any real data (pilot gate):** Postgres row-level security on every tenant table as a second layer, per-tenant encryption keys for attachments, and an isolation test suite run by someone other than the author. The prototype must not be described as having bank-grade tenant isolation until then.
