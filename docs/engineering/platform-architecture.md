# Platform architecture and parallel-agent workflow

**Date:** 2026-11-07  **Owner:** developer  **Status:** Accepted (Sriram, 2026-11-07). Decision record: ADR-011.

## What we are building
An **AI-native managed dispute operations service**: we run furnisher clients' FCRA disputes for them (ACDV first) with our own non-credentialed analysts, working in a platform where AI agents do the first pass and analysts review. The client sees a portal with volumes, SLA status, outcomes and examiner-ready audit exports. This follows the "$15-an-hour expert" model: the platform is what makes a trained generalist produce expert-quality, defensible investigations.

Everything is **synthetic** in Phase 1. Reference tables are `verified=false` placeholders.

## Runtime shape (ADR-001, ADR-002)
One Python 3.13 service: FastAPI + server-rendered Jinja2, Postgres 16 as the only stateful store (cases, artifacts, audit chain, jobs, config), a worker that drains the `jobs` table with `SKIP LOCKED`.

```
 fixture ACDVs ──► intake ──► classify/route ──► claims ──► evidence ──► compare ──► map claims ──► decide ──► draft+validate
 (AcdvSource)     (det.)      (LLM + det.)      (LLM)      (det. SoR)    (det.)       (LLM)          (det.)     (LLM + det.)
                                                                                                                    │
            audit chain (every step, same transaction) ◄──────────────────────────────────────────────────────────┤
                                                                                                                    ▼
                        analyst workbench /ops  ──►  approve / edit / escalate / second approval  ──►  package (ResponseSink stub)
                        client portal /client   ◄──  volumes, SLA, outcomes, audit exports (own tenant only)
```

**Product agents** (inside the platform): the classifier, claim extractor, claim-to-evidence mapper and drafter are LLM steps with no tools and schema-validated JSON output. Everything that decides an outcome is deterministic code (rules R-09/R-10). The validator (R-13) and the analyst gate every draft.

## Module map and ownership
Each module has one owning build agent. Modules talk only through `disputes/domain.py` types and the function signatures in each module's stub files. Pure modules do no I/O; only `workflow`, `audit`, `db` and `web` touch the database.

| Module | Path | Owner agent | Requirements | Pure? |
|---|---|---|---|---|
| Domain contract | `src/disputes/domain.py`, `config.py`, `reference.py`, `contracts_bridge.py` | foundation (change via a contract-only PR) | shared types | yes |
| DB + repository | `src/disputes/db/` | foundation; platform-core extends | ADR-001, ADR-008 | no |
| Audit chain | `src/disputes/audit/` | platform-core | R-21, R-23, R-32 | no |
| Workflow | `src/disputes/workflow/` (state machine, pipeline, jobs, worker) | platform-core | §6 states, ADR-002, R-15 fail-safe | no |
| CLI | `src/disputes/cli.py` | platform-core | ingest, worker, verify, anchor, backup/restore, seed | no |
| Intake | `src/disputes/intake/` | intake | R-02, R-03, R-04, R-05, R-14 (patterns), R-33 | yes |
| Rules | `src/disputes/rules/` | rules | R-08, R-09, R-10, R-29, R-35, B1 | yes |
| AI agents | `src/disputes/agents/`, `src/prompts/` | agents | R-06, R-07, R-11, R-12, R-13, R-15, R-30, R-34, R-36 | yes (LLM via injected client) |
| Web | `src/disputes/web/` | web | R-16 to R-20, R-22, R-24, R-18, client portal | no |
| Generator v1 | `src/synthgen/` | generator | R-26 v1, T2 red-team suite | yes |

## Rules for parallel build agents
1. **Work only in your module's paths** (plus your own tests named `tests/test_<module>_*.py` and your notes file `docs/engineering/stage-notes/<module>.md`). Do not edit `domain.py`, `db/migrations/0001_init.sql`, `STATUS.md`, `HANDOFFS.md`, `DECISIONS.md` or another module. If you need a contract change, describe it in your notes file and your PR; the integrator applies it.
2. **Migrations** use your number range (see `db/core.py`).
3. **Reference tables** you add go in `src/disputes/reference_tables/` in R-35 format with `verified=false` and a `source`.
4. **Branch** `agent/<module>`, one PR to `main`, title `[<module>] ...`. The integrator merges after the full suite passes.
5. **Tests are evidence.** Run `cd src && ../.venv/bin/python -m pytest` before you push. Report what ran and passed; never claim from reading code.
6. **No real data, no network** (the offline LLM backend is the default), no imports from `synthgen` in `src/disputes/` (test-enforced).

## Testing
`scripts/dev_postgres.sh start` runs a local Postgres on 127.0.0.1:5432. The `conn` fixture gives each test a fresh database cloned from a migrated template. CI (`.github/workflows/ci.yml`) runs the same suite against a Postgres service container.
