"""Case pipeline orchestrator. OWNER: platform-core agent.

Runs one dispute from intake to DRAFT_READY / ESCALATED / OUT_OF_SCOPE, persisting every
artifact (db.repo.put_artifact) and audit event (audit.chain.append_event), with state changes
via workflow.state_machine.transition. Each step commits atomically with its audit event
(ADR-002). Fail safe: any unexpected exception escalates the case, never drops it.

Steps (PRD §6):
 1 intake: map + validate (R-02), duplicate check (R-04: duplicate -> no case, log
   DUPLICATE_IGNORED), create case RECEIVED, attachments + limits (R-03/R-33), clock (R-05),
   suspicious content (R-14), repeat link (R-04)
 2 classify + route (R-06/R-07) -> CLASSIFIED -> INVESTIGATING | OUT_OF_SCOPE | ESCALATED
 3 claims (R-11) -> disputed months (R-08) -> evidence (R-08) -> comparison (R-09)
 4 claim mapping (R-11) -> decision (R-10)
 5 draft + validator (R-12/R-13) for VERIFY/MODIFY (and for escalated cases where a draft helps
   the reviewer, except ID fraud and OUT_OF_SCOPE: no draft)
 6 -> DRAFT_READY or ESCALATED (all reasons recorded on the case)
LLM_UNAVAILABLE at any step: escalate, keep deterministic results visible (R-15).

The pipeline depends on the other modules only through `Deps`, so it can be tested with fakes
while those modules are built in parallel.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Callable

from disputes.config import Config


@dataclass
class Deps:
    """Injected module functions (defaults wire the real modules; tests pass fakes)."""
    validate_dispute: Callable
    inspect_attachments: Callable
    compute_clock: Callable
    detect_suspicious: Callable
    find_repeat: Callable
    classify: Callable
    extract_claims: Callable
    disputed_months: Callable
    gather_evidence: Callable
    compare_months: Callable
    map_claims: Callable
    decide: Callable
    draft_narrative: Callable
    make_budget: Callable          # (cfg) -> CaseBudget
    sor: Any                       # SystemOfRecord for this tenant


def default_deps(sor, llm_client, cfg: Config) -> Deps:
    raise NotImplementedError


@dataclass(frozen=True)
class PipelineResult:
    case_id: str | None            # None when the intake was a duplicate
    state: str
    duplicate_of: str | None = None


def process_dispute(conn, *, tenant_id: str, dispute, deps: Deps, cfg: Config, now: datetime) -> PipelineResult:
    raise NotImplementedError
