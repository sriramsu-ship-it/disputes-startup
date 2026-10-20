# Engineering Status

**Last updated:** 2026-10-19 by developer

## Built
Nothing. There is no code in `src/`, no tests, no eval harness, and no eval baseline.

## Stubbed / faked
Nothing yet. When the prototype starts, the e-OSCAR intake and submit, the systems of record, and the response sink will be stubs or fixtures on synthetic data. Each will be listed here.

## Broken
N/A.

## Docs produced
- `docs/engineering/feasibility-core-loop.md`: feasibility of the MVP core loop (a draft for the PM)

## Next
1. The PM answers the questions in section 9 of the feasibility note and drafts a PRD.
2. Write ADR-001 to ADR-005 (stack, queue, audit log, integration boundary, LLM usage).
3. Build the synthetic dispute generator and a 50-item labelled pilot golden set.
4. Build the thin end-to-end prototype only after the PRD is approved.
