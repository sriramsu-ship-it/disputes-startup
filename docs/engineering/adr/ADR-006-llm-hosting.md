# ADR-006: LLM hosting — hosted, pinned model under zero-data-retention terms, synthetic data only

**Date:** 2026-10-20  **Status:** Proposed. **Sriram decides at the Stage 0 gate (PRD Q13).**  **Author:** developer

## Context
Phase 1 uses synthetic data only (CLAUDE.md, PRD §8). R-27 requires zero-retention terms "named and verified" here; R-30 requires an exact pinned model ID with no silent fallback. Bank and fintech hosting tolerance is unknown (U7, Phase 2), so the choice must be swappable to a model running inside a customer or cloud VPC without core changes. Latency and rate limits (U25) are unmeasured.

## Decision (proposed)
Use **Anthropic's Messages API directly, with Zero Data Retention (ZDR) enabled for our organisation**, and one exact model ID pinned in config (chosen in Stage 2, from the models the ZDR page lists as eligible). Calls go through `LlmClient`, which logs the requested and returned model IDs and fails with LLM_UNAVAILABLE on mismatch. Only Messages API features listed as ZDR-eligible are used (no Batch, Files API or code execution). Keep a second `LlmClient` implementation path for a cloud-hosted model in a VPC (e.g., Amazon Bedrock) for the pilot decision, not built in Phase 1.

**Disclosure:** the developer agent is itself built on an Anthropic model. That is a potential bias in this recommendation; the options table is the basis, and Sriram should weigh it.

## Provider terms: what I verified (2026-10-20)
| Claim | Source | Status |
|---|---|---|
| ZDR is enabled per organisation by Anthropic's account team after a request to sales; it is not self-serve | https://platform.claude.com/docs/en/manage-claude/api-and-data-retention | **A, read 2026-10-20** |
| Messages API, structured outputs (qualified: a bounded artifact is briefly retained), prompt caching are ZDR-eligible; Batch, Files API, code execution are not | same page | A, read 2026-10-20 |
| Some named models ("Covered Models") require 30-day retention and are not available under ZDR without express authorisation | same page | A, read 2026-10-20. Constrains which model we can pin |
| Even under ZDR, data flagged by trust-and-safety systems may be retained up to 2 years; data may be retained where required by law | same page | A, read 2026-10-20. **Matters for real data later; acceptable for synthetic** |
| Training use: the page says retained data is not used for training without express permission; it does not state the full training policy | same page | **Partly verified**; read the commercial terms before any real data |
| Amazon Bedrock: model providers have no access to Bedrock logs or customer prompts and completions | https://docs.aws.amazon.com/bedrock/latest/userguide/data-protection.html | A for that sentence only. The "Bedrock does not store prompts" statement appears in secondary sources but was **not** found on the page I fetched: **unverified** |
| Our org's ZDR status, contract terms, rate limits, p95 latency | none | **Not verified.** ZDR must be confirmed in writing before Stage 2 makes any call |

## Options considered
| Option | Pros | Cons | Cost to reverse |
|---|---|---|---|
| **Hosted vendor API with ZDR (proposed)** | Fastest to Stage 2; strong structured output; ZDR terms published | ZDR is a sales arrangement; T&S retention carve-out; a vendor sub-processor for banks | Low (behind `LlmClient`) |
| Cloud-hosted model in our cloud account (e.g., Bedrock) | Familiar to bank vendor-risk teams; data stays in one cloud contract | Retention terms not fully verified here; model availability and versions lag; more setup | Low |
| Self-hosted open-weight model in VPC | No third-party data flow | GPU ops; weaker structured output; heavy infra (needs its own ADR) | Medium |
| No LLM in Phase 1 (rules + human only) | Zero model risk | Cannot test the hypothesis (claims, drafts) | n/a |

## Consequences
Stage 2 is blocked until ZDR is confirmed in writing for the org that holds the API key (Sriram action). The pinned model must not be a "Covered Model". Changing the model ID triggers the full eval (R-25, R-30).

## Compliance and security impact
Synthetic data only, so no consumer PII leaves our boundary in Phase 1. API keys live in a secrets manager (ADR-009). Every call is audited with model ID and prompt hash. For a pilot the hosting choice is redone per partner (U7), with counsel reviewing the T&S retention carve-out.

## Revisit trigger
Any move to real data (pilot PRD); a partner requiring in-VPC hosting (U7); the provider changing ZDR eligibility or retiring the pinned model; p95 latency or rate limits failing R-28.
