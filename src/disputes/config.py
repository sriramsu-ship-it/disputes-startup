"""Runtime settings and PRD 'config' defaults.

Every threshold the PRD marks as config has its PRD default here. In the running app the
effective values live in the `config_versions` table (changes are audited ADMIN events,
R-21); `defaults()` seeds it. Modules take a `Config` argument rather than reading globals,
so tests can pass their own.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field, replace


@dataclass(frozen=True)
class Config:
    # R-03 / R-33 attachments
    min_chars_per_page: int = 200
    max_file_mb: int = 10
    max_pages_per_file: int = 50
    max_attachments_per_case: int = 10
    # R-04 repeats
    repeat_window_days: int = 90
    # R-05 clock
    internal_target_business_days_before_due: int = 3
    at_risk_business_days_before_target: int = 2
    # R-15 LLM budget
    llm_call_timeout_s: float = 60.0
    llm_case_budget_s: float = 90.0
    # 5 = four LLM steps (ADR-005) + one draft retry. PRD R-15 says 4; PM to confirm (agents stage notes).
    llm_max_calls_per_case: int = 5
    llm_retries: int = 1
    # R-12 draft
    narrative_max_words: int = 150
    # R-18 auth
    session_idle_timeout_min: int = 30
    # R-21 audit anchor
    anchor_interval_min: int = 15
    # R-23 / R-31 retention (placeholders; counsel, U10)
    audit_retention_years: int = 7
    non_audit_retention_days: int = 90
    # R-24 instrumentation
    idle_cutoff_s: int = 60
    # R-30 pinned model (ADR-006 proposes Anthropic API with ZDR; Sriram to confirm)
    # Default backend is "offline" (no network). The anthropic backend stays off until ZDR is
    # confirmed in writing for the key-holding org (ADR-006 §Consequences, Sriram action).
    llm_model_id: str = "claude-sonnet-5-5"
    # mode: "synthetic" (default) or "live". R-35: live refuses to start with any verified=false table.
    mode: str = "synthetic"

    def with_overrides(self, **kw) -> "Config":
        return replace(self, **kw)


def defaults() -> Config:
    return Config()


@dataclass(frozen=True)
class Settings:
    """Process settings from the environment (never secrets in the repo)."""
    database_url: str = field(default_factory=lambda: os.environ.get(
        "DISPUTES_DATABASE_URL", "postgresql://postgres@127.0.0.1:5432/disputes"))
    session_secret: str = field(default_factory=lambda: os.environ.get(
        "DISPUTES_SESSION_SECRET", "dev-only-not-a-secret"))
    llm_backend: str = field(default_factory=lambda: os.environ.get(
        "DISPUTES_LLM_BACKEND", "offline"))   # "offline" (deterministic, no network) | "anthropic"
    anchor_dir: str = field(default_factory=lambda: os.environ.get(
        "DISPUTES_ANCHOR_DIR", "/tmp/disputes-anchors"))


def settings() -> Settings:
    return Settings()
