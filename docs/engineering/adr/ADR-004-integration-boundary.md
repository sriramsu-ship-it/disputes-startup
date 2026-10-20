# ADR-004: Integration boundary — canonical `Dispute` and adapters with versioned fixtures

**Date:** 2026-10-20  **Status:** Proposed (contract skeleton built in Stage 0)  **Author:** developer

## Context
No live system is available: e-OSCAR access depends on a furnisher sponsor (U2), the ACDV schema and codes are unverified and changed in April 2026 (U6), the system of record is unknown (U9), and the Reg V direct-dispute fallback must reuse the core (PRD §11 #1). R-01 requires fixtures with `fixture_schema_version` and contract tests that pin their shape.

## Decision
Core logic sees only a channel-agnostic `Dispute` (tenant_id, channel, source_schema_version, raw_payload_sha256, synthetic, control number, CRA, received/due dates, account number, consumer name, codes, disputed months, free text, attachments). Four adapter protocols: `AcdvSource`, `SystemOfRecord`, `ResponseSink`, `LlmClient`; a `DirectDisputeSource` is added only if the Reg V fallback triggers. Stage 0 implements `FixtureAcdvSource`, `MockSystemOfRecord` and `StubResponseSink` in `src/disputes_core/contracts.py`. The mapper **does not validate**; it carries raw values (or None) so Stage 1 intake (R-02) decides INTAKE_INVALID. Unknown `fixture_schema_version` is rejected. Production code must not import the generator's label oracle (test-enforced, circularity guard).

## Options considered
| Option | Pros | Cons | Cost to reverse |
|---|---|---|---|
| **Canonical model + adapters + versioned fixtures** | Core is testable offline; swap fixtures for the real API later; Reg V reuses it | Mapping layer to maintain | Low |
| Code directly against the public e-OSCAR field names | Less mapping | Bakes an unverified schema into the core; breaks on schema change | High |
| Generic JSON pass-through | Flexible | No contract; untestable | Medium |

## Consequences
Easier: contract tests (8 in Stage 0) catch fixture drift; a real schema becomes a new `source_schema_version` plus mapper. Harder: the placeholder fixture shape will be wrong in places; every field mapping must be re-verified against the partner's developer guide (U6) before any non-synthetic run (R-35). **PRD note:** R-01 says fixtures are "shaped to the public e-OSCAR developer guide". The public pages do not publish the full payload (FEAS §1), so v0 fixtures carry only the R-01 required fields in our own placeholder names. I have **not** claimed they match e-OSCAR.

## Compliance and security impact
`raw_payload_sha256` ties every case to exactly what was received (audit input hash). Adapters are the trust boundary: everything from `AcdvSource` (free text, attachments, file names, metadata) is untrusted (ADR-007). The `synthetic` flag is carried into the canonical model so a non-synthetic run can be refused (R-35).

## Revisit trigger
A design partner shares the e-OSCAR developer guide or Stage access (U2, U6); the Reg V fallback triggers; a second system of record appears.
