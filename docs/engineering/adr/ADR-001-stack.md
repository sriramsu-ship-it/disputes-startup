# ADR-001: Stack — Python + FastAPI + Postgres monolith, server-rendered UI

**Date:** 2026-10-20  **Status:** Proposed  **Author:** developer

## Context
The MVP is a synthetic-data prototype built by the developer agent and reviewed by one founder in stages (PRD v1.1 §12). It needs a reliable relational store for cases, the audit chain (R-21), config versioning, and a review UI (R-16, R-17). Structured LLM outputs and the eval harness (R-25) favour Python. The bank buyer's InfoSec and model-risk reviewers (U30) will read this code, so the fewer moving parts the better.

## Decision
One deployable Python 3.13 service: FastAPI for HTTP, Postgres 16 as the only stateful store (cases, audit events, job queue, config), server-rendered HTML (Jinja2 templates plus minimal JS for R-24 focus timing), and S3-compatible object storage for attachments and the audit anchor (ADR-003). Dependencies are pinned with hashes. Stage 0 uses the standard library plus pinned test tools only (pytest, hypothesis, jsonschema).

## Options considered
| Option | Pros | Cons | Cost to reverse |
|---|---|---|---|
| **Python/FastAPI/Postgres monolith, server-rendered** | Boring; one process; SQL constraints and roles enforce audit rules; best LLM/eval tooling | Python is slower (irrelevant at MVP volume) | Medium |
| Same backend + React SPA | Richer review UI | A second build chain and API surface; more for one reviewer to audit | Low (UI only) |
| TypeScript/Node full stack | One language for UI and API | Weaker eval/stat tooling; scipy-class checks harder | High |
| Serverless functions + DynamoDB | Low ops | Insert-only and hash-chain serialisation are harder; weaker relational constraints; harder local tests | High |

## Consequences
Easier: local tests against a real Postgres, one deploy, SQL-level grants for insert-only audit. Harder: a polished UI; we accept a plain one (R-16 is about content, not polish). Must monitor: dependency CVEs (pinned, scanned in CI from Stage 1).

## Compliance and security impact
Fewer components means a smaller attack surface and a simpler data-flow diagram for vendor risk. Postgres roles give least privilege (app role cannot UPDATE/DELETE audit rows). TLS in transit and encryption at rest are deployment settings (ADR-009).

## Revisit trigger
A design partner requires a specific runtime or deployment target (e.g., their own Kubernetes/VPC), sustained load above ~50 cases/second, or a review UI requirement that server-rendered pages cannot meet in Phase 2 sessions.
