# ADR-011: Platform module boundaries for a managed service, built by parallel agents

**Date:** 2026-11-07  **Status:** Accepted (Sriram approved Stages 1-3 and the managed-service pivot, 2026-11-07)  **Author:** developer (integrator)

## Context
Sriram pivoted the go-to-market from selling software to furnishers to **running their disputes for them** (DECISIONS 2026-11-07), approved Stages 1-3 together, and asked for a platform that several agents can build at once and that itself runs AI agents. ADR-011 to 013 were reserved for Stage 1; this ADR takes 011. (012 and 013 remain reserved: 013 is the reference-table gate, built under R-35 in `rules/gate.py`.)

## Decision
1. One monolith (ADR-001) split into modules with a single shared contract (`src/disputes/domain.py`) and stub signatures per module. Deterministic modules (intake, rules) are pure functions; LLM steps (agents) take an injected client; only workflow, audit, db and web do I/O. The pipeline receives module functions through a `Deps` object, so each module can be built and tested in parallel with fakes.
2. Per-case results are stored as **versioned, insert-only JSON artifacts** (`case_artifacts`) plus a `cases` row for queue fields. This keeps the schema stable while modules evolve, and every artifact is hashed.
3. **Multi-tenant** from now on (supersedes ADR-008's "deferred"): see ADR-008 revision.
4. Two web surfaces: `/ops` (our analysts) and `/client` (client read-only portal).
5. Build process: each module is a branch `agent/<module>` and one PR; the integrator merges after the full suite passes on main.

## Options considered
| Option | Pros | Cons | Cost to reverse |
|---|---|---|---|
| **Modular monolith, shared contract, artifact store** | Parallel build without merge conflicts; one deploy; simple audit story | Contract changes need coordination | Low |
| Microservices per module | Independent deploys | Far more infra and attack surface for a prototype; distributed audit | High |
| Normalised tables per artifact | Strong typing in SQL | Every module change is a migration conflict between agents | Medium |

## Consequences
Easier: parallel agents, testing with fakes, adding the Reg V channel later. Harder: SQL queries over artifact contents (use the `cases` columns for anything the queue or portal filters on). Monitor: contract drift between modules (integration tests on the 200-case fixture set).

## Compliance and security impact
Artifacts are insert-only and hashed; the audit chain is unchanged (ADR-003). Holding several clients' data raises the bar on isolation: every query is tenant-scoped (test-enforced in `db/repo.py`), client users are bound to one tenant, and RLS is required before any real data (ADR-008 revision). As a service provider we also carry vendor-management scrutiny from each client (SOC 2, GLBA safeguards) — Phase 2 item, flagged to the PM.

## Revisit trigger
A client requires a dedicated deployment; module boundaries cause repeated cross-module PRs; queue or portal needs outgrow artifact JSON.
