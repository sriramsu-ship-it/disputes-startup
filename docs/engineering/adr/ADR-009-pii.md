# ADR-009: PII — synthetic only; masking in operational logs; encrypted, access-controlled audit store

**Date:** 2026-10-20  **Status:** Proposed  **Author:** developer

## Context
Dispute data is sensitive PII (names, SSNs, account numbers, consumer documents). Phase 1 is synthetic only (CLAUDE.md). R-27: mask names, SSN-like strings and account numbers to last 4 in operational logs and traces; the audit store is **not** masked but encrypted and access-controlled, with AUDITOR/ADMIN reads audited (R-21). R-31: 90-day placeholder for traces, logs and eval outputs. R-35: refuse non-synthetic mode while any reference table is unverified.

## Decision
1. **Synthetic only.** Every record carries `synthetic: true` (enforced as `const` in the Stage 0 JSON Schemas). Stage 1 adds a startup check: the app refuses any payload with `synthetic` not true unless an explicit non-synthetic mode is on, and that mode refuses to start while any table is `verified=false` (R-35).
2. **Recognisably fake values** (Stage 0, tested): invented surnames, state `ZZ`, ZIP `000xx`, phone area `000`, accounts `SYNACCT…`, SSN-shaped values with area 900-999 **and** group 00 (SSA never assigns these; https://www.ssa.gov/employer/randomizationfaqs.html, read 2026-10-20), PII-bait cards that fail Luhn. A test scans all generated text for real-looking SSNs and Luhn-valid 13-19-digit numbers.
3. **Operational logs/traces:** a logging filter masks SSN-shaped strings, account numbers and consumer names to last 4 before emission; tests assert it. Traces kept 90 days (config).
4. **Audit store:** unmasked, encrypted at rest (DB/volume encryption with KMS-managed keys), TLS in transit, access by role (AUDITOR/ADMIN read; app role insert/select), reads audited.
5. **Secrets** (DB credentials, LLM API key) in a secrets manager; never in the repo; `.gitignore` excludes local env files.
6. **LLM provider** under ZDR (ADR-006); synthetic data only.

## Options considered
| Option | Pros | Cons | Cost to reverse |
|---|---|---|---|
| **Mask ops logs, encrypt and restrict the audit store (proposed)** | Audit record stays complete for "why" (N4); logs are safe to ship to tooling | Audit store is high-value; must be guarded | Low |
| Mask everything including audit | Lower breach impact | Destroys the reconstruction the product exists for | High |
| Tokenise PII in a vault | Strong | Heavy infra for synthetic data | Medium |

## Consequences
Easier: dev and CI never touch real PII. Harder: realism of synthetic data (U20). Monitor: the PII scan test on every generated set; masking tests on log output.

## Compliance and security impact
Least privilege on the audit store; masking where data leaves the system of record (logs, traces, third-party tooling). Retention values are placeholders until counsel (U10). Before real data: independent security review (U30) and counsel (PRD §12).

## Revisit trigger
Any plan to load real data (pilot PRD); counsel on retention and deletion (U10); a partner's data-handling requirements.
