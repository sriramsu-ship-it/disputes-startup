"""LLM clients (ADR-005, ADR-006; R-15, R-30, R-36). OWNER: agents agent.

The model has NO tools and NO actions: it only returns JSON validated against a schema.
Untrusted text goes in as delimited data (R-14). Every call yields an LlmCallRecord that the
workflow writes to the audit log (R-21).

Backends:
- OfflineLlmClient: deterministic, no network, the default (Settings.llm_backend="offline").
  It implements the same prompt templates with transparent heuristics so the whole pipeline
  runs in CI and demos. It must NOT import synthgen.oracle or read labels (test-enforced).
- AnthropicLlmClient: Messages API, pinned model ID (R-30: mismatch -> LlmUnavailable, no
  fallback). Off until ZDR is confirmed (ADR-006).
"""
from __future__ import annotations

from typing import Protocol

from disputes.domain import LlmCallRecord


class LlmUnavailable(RuntimeError):
    """Timeout, error after retry, budget exhausted, or model-ID mismatch -> LLM_UNAVAILABLE."""


class LlmClient(Protocol):
    model_id: str

    def complete_json(self, prompt_template_id: str, data: dict, schema: dict) -> tuple[dict, LlmCallRecord]:
        """Render template `prompt_template_id` (src/prompts/<id>.md) with `data`, call the model,
        validate against `schema`, return (output, record). Raises LlmUnavailable."""
        ...


class CaseBudget:
    """R-15: ≤ cfg.llm_max_calls_per_case calls and ≤ cfg.llm_case_budget_s seconds per case;
    1 retry with backoff per call. Collects LlmCallRecords for the audit log and cost (R-36)."""

    def __init__(self, client: LlmClient, cfg):
        raise NotImplementedError

    def call(self, prompt_template_id: str, data: dict, schema: dict) -> dict:
        raise NotImplementedError

    @property
    def records(self) -> list[LlmCallRecord]:
        raise NotImplementedError


def make_client(backend: str, cfg) -> LlmClient:
    raise NotImplementedError
