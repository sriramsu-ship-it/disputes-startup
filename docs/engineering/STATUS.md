# Engineering Status

**Last updated:** 2026-10-19 by developer

## Built
Nothing. There is no code in `src/`. There are no tests, no eval harness and no eval baseline. No ADRs have been written.

## Stubbed / faked
Nothing yet. When the prototype starts, these will be stubs or fixtures on synthetic data, and each will be listed here:
- e-OSCAR intake (`AcdvSource` fixtures on an **unverified** schema)
- the system of record (mock, which supplies days past due for each month)
- the response sink (stub)
- the reference tables (dispute codes, Metro 2 ratings, holidays), each tagged `verified=false`

## Broken
N/A.

## Docs produced
- `docs/engineering/feasibility-core-loop.md`: feasibility of the MVP core loop
- `docs/engineering/prd-feasibility-review.md`: review of PRD MVP v0. Verdict: feasible with changes. Effort: 10-12 weeks with 2 engineers, 18-21 weeks with 1.

## Next
1. The PM applies or rejects the review's §8 changes. The founders confirm PRD Q1-Q3, including the tiered eval design.
2. Draft ADR-001 to 005, 010, 011 and 013. Set up the repo, CI and DB skeleton.
3. Build synthetic generator v0 and a 50-case pilot set for the founders' kappa trial (U8). Build the audit chain and `verify`, with tests.
4. Nothing past this point until Q1-Q3 are confirmed (PM handoff).
