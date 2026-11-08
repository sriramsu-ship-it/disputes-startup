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

Implementation notes (platform-core):
- Transactions: every DB step runs in `with conn.transaction()`. If the caller already has a
  transaction open, the steps become savepoints and the caller commits.
- INTAKE_INVALID stops at intake (no LLM call, R-02). DOC_UNREADABLE and BREACHED are recorded
  and carried as upstream escalations; classification and investigation still run so the
  reviewer sees deterministic results, and the case ends ESCALATED.
- Repeat link (R-04) needs the category set, so it runs right after classification
  (repeat key = account + category). Cases stopped at intake are not repeat-linked.
- ESCALATE_FRAUD / MULTI_ISSUE / CLASS_CONFLICT and OUT_OF_SCOPE stop after classification
  (no investigation, no draft). ID fraud sets priority=100.
- Investigated cases are always drafted (unless the LLM is down) so the reviewer has a draft,
  including escalated ones. A DRAFT_INVALID re-runs `decide` with DRAFT_INVALID upstream so the
  stored Decision matches the final escalation set (DECISION artifact v2).
- LlmUnavailable at any LLM step: later LLM steps are skipped, deterministic steps still run
  (evidence, comparison, decision), the case ends ESCALATED / LLM_UNAVAILABLE.
- Any other exception: the failed step's writes roll back, a PIPELINE_ERROR event records the
  error, and the case moves to ESCALATED (STATE_CHANGED reason "SYSTEM_ERROR"; the closed
  EscalationReason list has no system-error value, see the contract-change request in
  docs/engineering/stage-notes/platform-core.md).
"""
from __future__ import annotations

import logging
import traceback
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from typing import Any, Callable

import psycopg

from disputes.audit.chain import append_event, sha256_hex
from disputes.config import Config
from disputes.db import repo
from disputes.domain import (
    ActorType, ArtifactKind, CaseState as S, ClockState, EscalationReason as E, IntakeResult, Outcome, Route,
    to_jsonable,
)
from disputes.workflow import state_machine

log = logging.getLogger(__name__)

SYSTEM = "system:pipeline"
FRAUD_PRIORITY = 100
PIPELINE_VERSION = "1.0.0"


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
    """Wire the real module functions (imported lazily: they are built in parallel)."""
    from disputes.agents import claims as agent_claims
    from disputes.agents import classify as agent_classify
    from disputes.agents import draft as agent_draft
    from disputes.agents import llm as agent_llm
    from disputes.intake import attachments, clock, dedup, suspicious, validate
    from disputes.rules import compare, evidence, outcome

    return Deps(
        validate_dispute=validate.validate_dispute,
        inspect_attachments=attachments.inspect_attachments,
        compute_clock=clock.compute_clock,
        detect_suspicious=suspicious.detect,
        find_repeat=dedup.find_repeat,
        classify=agent_classify.classify,
        extract_claims=agent_claims.extract_claims,
        disputed_months=evidence.disputed_months,
        gather_evidence=evidence.gather_evidence,
        compare_months=compare.compare_months,
        map_claims=agent_claims.map_claims,
        decide=outcome.decide,
        draft_narrative=agent_draft.draft_narrative,
        make_budget=lambda c: agent_llm.CaseBudget(llm_client, c),
        sor=sor,
    )


@dataclass(frozen=True)
class PipelineResult:
    case_id: str | None            # None when the intake was a duplicate
    state: str
    duplicate_of: str | None = None


class NonSyntheticRefused(ValueError):
    """ADR-009 §1: a payload with synthetic != true is refused in synthetic mode (no case, no storage)."""


class _LlmDown(Exception):
    pass


# --------------------------------------------------------------------------- helpers
def _llm_unavailable_type():
    try:
        from disputes.agents.llm import LlmUnavailable
        return LlmUnavailable
    except Exception:  # pragma: no cover - the agents module always defines it
        return _LlmDown


def _parse_date(s) -> date | None:
    if isinstance(s, date) and not isinstance(s, datetime):
        return s
    if not isinstance(s, str):
        return None
    try:
        return date.fromisoformat(s.strip())
    except ValueError:
        return None


def _strip(s) -> str | None:
    return s.strip() if isinstance(s, str) and s.strip() else None


@dataclass
class _Run:
    conn: Any
    tenant_id: str
    dispute: Any
    deps: Deps
    cfg: Config
    now: datetime
    case_id: str | None = None
    reasons: list = field(default_factory=list)          # ordered, de-duplicated EscalationReason
    reason_sources: dict = field(default_factory=dict)   # reason -> step that raised it
    budget: Any = None
    logged_records: int = 0
    llm_down: bool = False
    step: str = "init"
    classification: Any = None
    decision: Any = None
    comparisons: list = field(default_factory=list)
    decided_with: tuple = ()

    # -- persistence primitives (call inside a transaction)
    def event(self, event_type: str, payload: dict, *, actor_type=ActorType.SYSTEM, actor_id=SYSTEM,
              case_id: str | None | object = ...):
        cid = self.case_id if case_id is ... else case_id
        return append_event(self.conn, tenant_id=self.tenant_id, case_id=cid, event_type=event_type,
                            actor_type=actor_type, actor_id=actor_id, actor_role=None,
                            payload=to_jsonable(payload))

    def artifact(self, kind: ArtifactKind, data, created_by: str = SYSTEM) -> dict:
        row = repo.put_artifact(self.conn, tenant_id=self.tenant_id, case_id=self.case_id, kind=kind,
                                data=data, created_by=created_by)
        return {"kind": str(kind), "version": row["version"], "sha256": row["data_sha256"]}

    def fields(self, **kw):
        return repo.update_case_fields(self.conn, tenant_id=self.tenant_id, case_id=self.case_id, **kw)

    def move(self, to: S, reason: str | None = None, detail: dict | None = None):
        return state_machine.transition(self.conn, tenant_id=self.tenant_id, case_id=self.case_id, to=to,
                                        actor_type=ActorType.SYSTEM, actor_id=SYSTEM, reason=reason,
                                        detail=to_jsonable(detail or {}))

    def state(self) -> str:
        return repo.get_case(self.conn, tenant_id=self.tenant_id, case_id=self.case_id)["state"]

    def add_reasons(self, reasons, source: str):
        for r in reasons or ():
            r = E(r)
            if r not in self.reasons:
                self.reasons.append(r)
                self.reason_sources[r.value] = source

    def flush_model_calls(self, step: str):
        """One MODEL_CALL event per new LlmCallRecord (R-15, R-21, R-30, R-36). In a transaction."""
        if self.budget is None:
            return
        try:
            records = list(self.budget.records)
        except Exception:  # a budget that cannot report its calls must not hide the step result
            records = []
        for rec in records[self.logged_records:]:
            self.event("MODEL_CALL", {"step": step, **to_jsonable(rec)}, actor_type=ActorType.MODEL,
                       actor_id=f"model:{getattr(rec, 'model_id', 'unknown')}")
        self.logged_records = len(records)

    def llm(self, step: str, fn: Callable, *args):
        """Run an LLM-backed step. LlmUnavailable -> mark LLM down, log the calls, return None."""
        if self.llm_down:
            return None
        try:
            return fn(*args)
        except _llm_unavailable_type() as e:
            self.llm_down = True
            with self.conn.transaction():
                self.flush_model_calls(step)
                self.add_reasons([E.LLM_UNAVAILABLE], step)
                self.event("LLM_UNAVAILABLE", {"step": step, "error": str(e)[:2000],
                                               "error_type": type(e).__name__})
            return None


# --------------------------------------------------------------------------- entry point
def process_dispute(conn, *, tenant_id: str, dispute, deps: Deps, cfg: Config, now: datetime) -> PipelineResult:
    """Run one canonical Dispute through the pipeline. Returns the case ID and final state.

    Raises only for: a tenant mismatch or non-synthetic payload in synthetic mode (before any
    write), or a database failure while recording a fail-safe escalation (the job layer retries).
    """
    if getattr(dispute, "tenant_id", tenant_id) != tenant_id:
        raise ValueError(f"dispute tenant {dispute.tenant_id!r} does not match {tenant_id!r}")
    if cfg.mode == "synthetic" and getattr(dispute, "synthetic", False) is not True:
        raise NonSyntheticRefused("synthetic mode refuses a payload not marked synthetic=true (ADR-009)")
    if now.tzinfo is None:
        raise ValueError("now must be timezone-aware")

    run = _Run(conn=conn, tenant_id=tenant_id, dispute=dispute, deps=deps, cfg=cfg, now=now)
    dup = _create_case_or_duplicate(run)
    if dup is not None:
        return dup
    try:
        _run_steps(run)
    except Exception as e:  # fail safe (R-15, ADR-002): never drop a case
        log.error("pipeline error case=%s step=%s type=%s", run.case_id, run.step, type(e).__name__)
        _escalate_on_error(run, e)
    with conn.transaction():
        return PipelineResult(case_id=run.case_id, state=run.state())


# --------------------------------------------------------------------------- step 1a: case or duplicate
def _create_case_or_duplicate(run: _Run) -> PipelineResult | None:
    d, conn, tenant_id = run.dispute, run.conn, run.tenant_id
    control = _strip(d.control_number)
    for _attempt in range(2):
        try:
            with conn.transaction():
                if control:
                    orig = repo.find_case_by_control_number(conn, tenant_id=tenant_id, control_number=control)
                    if orig is not None:
                        repo.record_duplicate(conn, tenant_id=tenant_id, control_number=control,
                                              original_case_id=orig["case_id"],
                                              raw_payload_sha256=d.raw_payload_sha256)
                        run.event("DUPLICATE_IGNORED", {
                            "control_number": control, "original_case_id": orig["case_id"],
                            "raw_payload_sha256": d.raw_payload_sha256, "rule_id": "R-04.DUPLICATE"},
                            case_id=None)
                        return PipelineResult(case_id=None, state="DUPLICATE_IGNORED",
                                              duplicate_of=orig["case_id"])
                _insert_case(run, control)
                return None
        except psycopg.errors.UniqueViolation:
            run.case_id = None      # a concurrent intake took the control number: retry as a duplicate
            continue
    raise RuntimeError("could not create case or record duplicate")


def _insert_case(run: _Run, control: str | None) -> None:
    d, conn = run.dispute, run.conn
    day = run.now.astimezone(timezone.utc).date()
    run.case_id = repo.next_case_id(conn, tenant_id=run.tenant_id, day=day)
    acct = _strip(d.account_number)
    repo.insert_case(conn, tenant_id=run.tenant_id, case={
        "case_id": run.case_id, "channel": d.channel or "ACDV", "control_number": control, "cra": _strip(d.cra),
        "account_number": acct, "account_last4": acct[-4:] if acct else None,
        "date_received": _parse_date(d.date_received), "response_due_date": _parse_date(d.response_due_date),
        "state": S.RECEIVED.value, "raw_payload_sha256": d.raw_payload_sha256, "synthetic": bool(d.synthetic)})
    art = run.artifact(ArtifactKind.DISPUTE, d)
    seen: set[str] = set()
    stored = []
    for a in d.attachments or ():
        att_id = str(a.attachment_id)
        while att_id in seen:            # malformed input with repeated IDs: keep every file
            att_id += "#dup"
        seen.add(att_id)
        page_count = a.page_count if isinstance(a.page_count, int) and not isinstance(a.page_count, bool) else 0
        repo.insert_attachment(conn, tenant_id=run.tenant_id, case_id=run.case_id, att={
            "attachment_id": att_id, "file_name": str(a.file_name or ""), "media_type": str(a.media_type or ""),
            "page_count": page_count, "sha256": str(a.sha256 or ""),
            "extracted_text": str(a.extracted_text or "").replace("\x00", ""), "metadata": a.metadata or {}})
        stored.append({"attachment_id": att_id, "sha256": a.sha256})
    run.event("CASE_CREATED", {
        "channel": d.channel, "control_number": control, "raw_payload_sha256": d.raw_payload_sha256,
        "source_schema_version": d.source_schema_version, "synthetic": d.synthetic, "artifact": art,
        "attachments": stored, "pipeline_version": PIPELINE_VERSION})


# --------------------------------------------------------------------------- steps 1b-6
def _run_steps(run: _Run) -> None:
    d, deps, cfg = run.dispute, run.deps, run.cfg

    # ---- 1b intake checks (pure, no LLM)
    run.step = "intake"
    v_esc, v_errors = deps.validate_dispute(d)
    v_esc, v_errors = list(v_esc or ()), list(v_errors or ())
    due = _parse_date(d.response_due_date)
    received = _parse_date(d.date_received)
    if E.INTAKE_INVALID not in v_esc and (due is None or received is None):
        v_esc.append(E.INTAKE_INVALID)      # defence in depth: the clock needs both dates
        v_errors.append("pipeline: date_received/response_due_date missing or not ISO 8601")
    findings, too_many = deps.inspect_attachments(tuple(d.attachments or ()), cfg)
    findings = tuple(findings)
    clock = deps.compute_clock(due, run.now, cfg) if due is not None else None
    intake_esc = list(v_esc)
    if too_many or any(not f.readable for f in findings):
        intake_esc.append(E.DOC_UNREADABLE)
    if clock is not None and clock.state == ClockState.BREACHED:
        intake_esc.append(E.BREACHED)
    suspicion = deps.detect_suspicious(d, findings)
    run.attachment_findings = findings
    intake = IntakeResult(valid=E.INTAKE_INVALID not in intake_esc, escalations=tuple(dict.fromkeys(intake_esc)),
                          clock=clock, attachment_findings=findings, errors=tuple(v_errors))
    run.add_reasons(intake.escalations, "intake")
    with run.conn.transaction():
        a_int = run.artifact(ArtifactKind.INTAKE, intake)
        a_sus = run.artifact(ArtifactKind.SUSPICION, suspicion)
        upd = {"suspicion_level": str(suspicion.level), "escalation_reasons": [r.value for r in run.reasons]}
        if clock is not None:
            upd.update(clock_state=str(clock.state), internal_target_date=clock.internal_target,
                       response_due_date=clock.due_date)
        run.fields(**upd)
        run.event("INTAKE_VALIDATED", {
            "rule_ids": ["R-02", "R-03", "R-05", "R-33"], "valid": intake.valid,
            "escalations": intake.escalations, "errors": intake.errors, "too_many_attachments": too_many,
            "attachment_findings": findings, "clock": clock, "artifact": a_int})
        run.event("SUSPICION_CHECKED", {"rule_id": "R-14", "level": suspicion.level,
                                        "patterns_version": suspicion.patterns_version,
                                        "matches": len(suspicion.matches), "artifact": a_sus})
    if not intake.valid:                    # R-02: escalate, no LLM call
        _finish(run)
        return

    # ---- 2 classify + route
    run.step = "classify"
    run.budget = deps.make_budget(cfg)
    classification = run.llm("classify", deps.classify, d, run.budget)
    if classification is None:              # LLM down: keep deterministic investigation visible
        _deterministic_only(run, claims=[])
        _finish(run)
        return
    run.classification = classification
    with run.conn.transaction():
        run.flush_model_calls("classify")
        a_cls = run.artifact(ArtifactKind.CLASSIFICATION, classification)
        run.fields(categories=sorted(str(c) for c in classification.categories))
        run.event("CLASSIFIED", {"rule_ids": ["R-06", "R-07"], "categories": classification.categories,
                                 "code_categories": classification.code_categories,
                                 "llm_categories": classification.llm_categories,
                                 "fraud_signal_sources": classification.fraud_signal_sources,
                                 "llm_confidence": classification.llm_confidence, "route": classification.route,
                                 "escalations": classification.escalations, "artifact": a_cls})
        run.move(S.CLASSIFIED, reason=str(classification.route))
    _link_repeat(run, received, classification)

    run.add_reasons(classification.escalations, "classify")
    route = Route(classification.route)
    if route == Route.ESCALATE_FRAUD:
        run.add_reasons([E.ID_FRAUD_SUSPECTED], "classify")
        with run.conn.transaction():
            run.fields(priority=FRAUD_PRIORITY)
        _finish(run, outcome=Outcome.ESCALATED)
        return
    if route == Route.ESCALATE_MULTI_ISSUE:
        run.add_reasons([E.MULTI_ISSUE], "classify")
        _finish(run, outcome=Outcome.ESCALATED)
        return
    if route == Route.ESCALATE_CLASS_CONFLICT:
        run.add_reasons([E.CLASS_CONFLICT], "classify")
        _finish(run, outcome=Outcome.ESCALATED)
        return
    if route == Route.OUT_OF_SCOPE:
        _finish(run, outcome=Outcome.OUT_OF_SCOPE)
        return
    with run.conn.transaction():
        run.move(S.INVESTIGATING, reason=str(route))

    # ---- 3 claims -> months -> evidence -> comparison
    run.step = "claims"
    extracted = run.llm("extract_claims", deps.extract_claims, d, run.budget)
    claims = []
    if extracted is not None:
        claims, c_esc = extracted
        claims = list(claims)
        run.add_reasons(c_esc, "extract_claims")
        guard = not claims and _has_consumer_narrative(d)
        if guard:   # defence in depth: a letter we extracted nothing from must never be verified (R-10 B1)
            run.add_reasons([E.CLAIM_UNRESOLVED], "no_claims_guard")
        with run.conn.transaction():
            run.flush_model_calls("extract_claims")
            a = run.artifact(ArtifactKind.CLAIMS, claims)
            run.event("CLAIMS_EXTRACTED", {"rule_id": "R-11", "claims": len(claims),
                                           "escalations": tuple(c_esc or ()), "no_claims_guard": guard,
                                           "artifact": a})
    evidence = _investigate(run, claims)

    # ---- 4 mapping + decision
    run.step = "map_claims"
    if claims and not run.llm_down:
        mapped_res = run.llm("map_claims", deps.map_claims, claims, evidence, run.budget)
        if mapped_res is not None:
            mapped, m_esc = mapped_res
            claims = list(mapped)
            run.add_reasons(m_esc, "map_claims")
            with run.conn.transaction():
                run.flush_model_calls("map_claims")
                a = run.artifact(ArtifactKind.CLAIMS, claims)
                run.event("CLAIMS_MAPPED", {"rule_id": "R-11", "claims": len(claims),
                                            "findings": [str(c.finding) if c.finding else None for c in claims],
                                            "escalations": tuple(m_esc or ()), "artifact": a})
    run.step = "decide"
    decision = _decide(run, claims, evidence)

    # ---- 5 draft
    run.step = "draft"
    if not run.llm_down:
        draft = run.llm("draft", deps.draft_narrative, decision, claims, evidence, run.budget)
        if draft is not None:
            if not draft.valid:
                run.add_reasons([E.DRAFT_INVALID], "draft")
            with run.conn.transaction():
                run.flush_model_calls("draft")
                a = run.artifact(ArtifactKind.DRAFT, draft)
                run.event("DRAFT_GENERATED", {"rule_ids": ["R-12", "R-13"], "valid": draft.valid,
                                              "validator_errors": draft.validator_errors,
                                              "attempts": draft.attempts, "sentences": len(draft.sentences),
                                              "template_library_version": draft.template_library_version,
                                              "artifact": a})
    if any(r not in run.decided_with and r not in decision.escalation_reasons for r in run.reasons):
        decision = _decide(run, claims, evidence)   # final decision reflects every upstream reason

    # ---- 6 final state
    _finish(run, outcome=Outcome(decision.outcome))


def _investigate(run: _Run, claims: list) -> list:
    """Disputed months, evidence and comparison (deterministic, R-08/R-09). Returns evidence."""
    d, deps = run.dispute, run.deps
    run.step = "evidence"
    claim_months = {m for c in claims for m in (c.months or ())}
    months = list(deps.disputed_months(d, claim_months))
    if not months:
        run.add_reasons([E.MONTHS_UNDETERMINED], "evidence")
    evidence = list(deps.gather_evidence(d, deps.sor, months, run.now))
    run.step = "compare"
    comparisons = list(deps.compare_months(months, evidence))
    run.comparisons = comparisons
    with run.conn.transaction():
        a_ev = run.artifact(ArtifactKind.EVIDENCE, evidence)
        run.event("EVIDENCE_GATHERED", {
            "rule_id": "R-08", "disputed_months": months, "claim_months": sorted(claim_months),
            "items": [{"evidence_id": e.evidence_id, "kind": e.kind, "source": e.source, "sha256": e.sha256}
                      for e in evidence], "artifact": a_ev})
        a_cmp = run.artifact(ArtifactKind.COMPARISON, comparisons)
        run.event("MONTHS_COMPARED", {"rule_id": "R-09", "results": {c.month: str(c.result) for c in comparisons},
                                      "artifact": a_cmp})
        if E.MONTHS_UNDETERMINED in run.reasons:
            run.fields(escalation_reasons=[r.value for r in run.reasons])
    return evidence


NARRATIVE_MIN_WORDS = 25


def _has_consumer_narrative(d) -> bool:
    """True when the consumer sent a letter with enough text to contain claims. A letter we could
    not extract a single claim from is a model miss, not evidence that nothing was claimed."""
    words = sum(len((a.extracted_text or "").split()) for a in (d.attachments or ()))
    return words >= NARRATIVE_MIN_WORDS


def _recheck_suspicion(run: _Run) -> None:
    """R-14: intake runs the detector before any model call, so a model flag raised later
    (classify / claims) is applied here by re-running the detector with llm_flag=True."""
    budget = getattr(run, "budget", None)
    if budget is None or getattr(run, "llm_flag_applied", False) or not getattr(budget, "suspicious_flag", False):
        return
    run.llm_flag_applied = True
    suspicion = run.deps.detect_suspicious(run.dispute, getattr(run, "attachment_findings", ()), llm_flag=True)
    with run.conn.transaction():
        a = run.artifact(ArtifactKind.SUSPICION, suspicion)
        run.fields(suspicion_level=str(suspicion.level))
        run.event("SUSPICION_CHECKED", {"rule_id": "R-14", "level": suspicion.level, "llm_flag": True,
                                        "patterns_version": suspicion.patterns_version,
                                        "matches": len(suspicion.matches), "artifact": a})


def _decide(run: _Run, claims: list, evidence: list):
    _recheck_suspicion(run)
    upstream = tuple(r for r in run.reasons)
    budget = getattr(run, "budget", None)
    decision = run.deps.decide(classification=run.classification, comparisons=run.comparisons,
                               evidence=evidence, claims=claims, upstream_escalations=upstream,
                               llm_note_flag=bool(getattr(budget, "note_conflict", False)))
    run.decision = decision
    run.decided_with = upstream
    run.add_reasons(decision.escalation_reasons, "decide")
    with run.conn.transaction():
        a = run.artifact(ArtifactKind.DECISION, decision)
        run.fields(proposed_outcome=str(decision.outcome))
        run.event("RULE_EVALUATED", {"rule_id": "R-10", "rules_version": decision.rules_version,
                                     "table_versions": decision.table_versions, "outcome": decision.outcome,
                                     "escalation_reasons": decision.escalation_reasons,
                                     "corrections": decision.corrections, "firings": decision.firings,
                                     "upstream_escalations": upstream, "artifact": a})
    return decision


def _deterministic_only(run: _Run, claims: list) -> None:
    """LLM down before routing: still compute evidence + comparison so the reviewer sees them."""
    _investigate(run, claims)


def _link_repeat(run: _Run, received: date | None, classification) -> None:
    acct = _strip(run.dispute.account_number)
    if not acct or received is None:
        return
    with run.conn.transaction():
        prior = [p for p in repo.prior_cases_for_account(run.conn, tenant_id=run.tenant_id, account_number=acct)
                 if p["case_id"] != run.case_id]
        if not prior:
            return
        hit = run.deps.find_repeat(date_received=received, categories={str(c) for c in classification.categories},
                                   prior_cases=prior, window_days=run.cfg.repeat_window_days)
        if not hit:
            return
        run.fields(repeat_of_case_id=hit["case_id"])
        intake = repo.latest_artifact(run.conn, tenant_id=run.tenant_id, case_id=run.case_id,
                                      kind=ArtifactKind.INTAKE)
        data = dict(intake["data"]) if intake else {}
        data["repeat_of_case_id"] = hit["case_id"]
        a = run.artifact(ArtifactKind.INTAKE, data)
        run.event("REPEAT_LINKED", {"rule_id": "R-04.REPEAT", "repeat_of_case_id": hit["case_id"],
                                    "prior_proposed_outcome": hit.get("proposed_outcome"),
                                    "prior_final_outcome": hit.get("final_outcome"),
                                    "window_days": run.cfg.repeat_window_days, "artifact": a})


def _finish(run: _Run, outcome: Outcome | None = None) -> None:
    """Final state: ESCALATED if any reason, else OUT_OF_SCOPE or DRAFT_READY."""
    run.step = "finish"
    with run.conn.transaction():
        cur = run.state()
        upd = {"escalation_reasons": [r.value for r in run.reasons]}
        if run.reasons:
            target = S.ESCALATED
            if run.decision is None:
                upd["proposed_outcome"] = Outcome.ESCALATED.value
        elif outcome == Outcome.OUT_OF_SCOPE:
            target = S.OUT_OF_SCOPE
            upd["proposed_outcome"] = Outcome.OUT_OF_SCOPE.value
        else:
            target = S.DRAFT_READY
        run.fields(**upd)
        detail = {"escalation_reasons": [r.value for r in run.reasons], "reason_sources": run.reason_sources}
        if run.decision is not None:
            detail["firings"] = run.decision.firings
            detail["rules_version"] = run.decision.rules_version
        if cur != target.value:
            run.move(target, reason=",".join(r.value for r in run.reasons) or str(outcome or target), detail=detail)


def _escalate_on_error(run: _Run, exc: Exception) -> None:
    """Fail safe: record the error and escalate. Re-raises only if the DB itself fails here."""
    if run.conn.info.transaction_status == psycopg.pq.TransactionStatus.INERROR:
        run.conn.rollback()
    tb = traceback.format_exception(type(exc), exc, exc.__traceback__)
    with run.conn.transaction():
        if run.budget is not None:
            run.flush_model_calls(run.step)
        run.event("PIPELINE_ERROR", {"step": run.step, "error_type": type(exc).__name__,
                                     "error": str(exc)[:2000], "traceback_sha256": sha256_hex("".join(tb))})
        run.fields(escalation_reasons=[r.value for r in run.reasons])
        cur = run.state()
        if state_machine.can_transition(cur, S.ESCALATED):
            run.move(S.ESCALATED, reason="SYSTEM_ERROR",
                     detail={"step": run.step, "error_type": type(exc).__name__,
                             "escalation_reasons": [r.value for r in run.reasons]})


def escalate_stuck_case(conn, *, tenant_id: str, control_number: str | None, error: str) -> str | None:
    """Worker fail-safe hook: if a case for this control number exists and is still in an
    automated pre-review state, escalate it. Returns the case_id escalated, or None."""
    if not control_number:
        return None
    with conn.transaction():
        case = repo.find_case_by_control_number(conn, tenant_id=tenant_id, control_number=control_number.strip())
        if case is None or case["state"] not in (S.RECEIVED, S.CLASSIFIED, S.INVESTIGATING):
            return None
        append_event(conn, tenant_id=tenant_id, case_id=case["case_id"], event_type="PIPELINE_ERROR",
                     actor_type=ActorType.SYSTEM, actor_id=SYSTEM, actor_role=None,
                     payload={"step": "worker", "error": error[:2000]})
        state_machine.transition(conn, tenant_id=tenant_id, case_id=case["case_id"], to=S.ESCALATED,
                                 actor_type=ActorType.SYSTEM, actor_id=SYSTEM, reason="SYSTEM_ERROR",
                                 detail={"step": "worker"})
        return case["case_id"]


__all__ = ["Deps", "PipelineResult", "default_deps", "process_dispute", "NonSyntheticRefused",
           "escalate_stuck_case"]
