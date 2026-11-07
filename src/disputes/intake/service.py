"""Intake service: R-02, R-03/R-33, R-04 (repeats), R-05 and R-14 in one pure call. OWNER: intake agent.

The pipeline may call this or the individual functions. Duplicates (same control number) are
NOT decided here: they need a database lookup, which the workflow layer does before creating a
case (R-04 DUPLICATE_IGNORED). `duplicate_of_case_id` is therefore always None from this function.
"""
from __future__ import annotations

from datetime import datetime

from disputes import reference
from disputes.config import Config
from disputes.contracts_bridge import Dispute
from disputes.domain import ClockState, EscalationReason, IntakeResult, SuspicionResult
from disputes.intake.attachments import inspect_attachments
from disputes.intake.clock import compute_clock
from disputes.intake.dedup import find_repeat
from disputes.intake.suspicious import detect
from disputes.intake.validate import parse_iso_date, validate_dispute

CODE_TABLE = "dispute_code_map"


def code_categories(codes) -> set[str]:
    """Categories from the deterministic dispute-code table (R-06 code side; verified=false, U6).
    Used only as the repeat key at intake; unknown codes contribute nothing."""
    by_code = {e["code"]: e["categories"] for e in reference.load(CODE_TABLE)["entries"]}
    out: set[str] = set()
    for c in codes or ():
        if isinstance(c, str):
            out |= set(by_code.get(c.strip(), ()))
    return out


def run_intake(dispute: Dispute, now: datetime, cfg: Config,
               prior_cases: list[dict] | None = None, *, llm_flag: bool = False
               ) -> tuple[IntakeResult, SuspicionResult]:
    """Deterministic intake for one dispute. Never raises on malformed dispute content (it
    escalates instead); raises ValueError only if `now` is not timezone-aware (a caller bug).

    Escalations, in this order, all recorded: INTAKE_INVALID (R-02/R-05), BREACHED (R-05, due
    date already ended at intake), DOC_UNREADABLE (R-03/R-33: any unreadable attachment,
    archive, over a size/page limit, or more than cfg.max_attachments_per_case attachments).
    The clock is computed whenever the due date parses, even if another field is invalid, so
    the queue can still sort the case by deadline.
    """
    if not isinstance(now, datetime) or now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("run_intake: `now` must be a timezone-aware datetime")

    escalations: list[EscalationReason] = []
    v_esc, errors = validate_dispute(dispute)
    escalations += v_esc
    errors = list(errors)

    clock = None
    due = parse_iso_date(getattr(dispute, "response_due_date", None))
    if due is not None:
        clock = compute_clock(due, now, cfg)
        if clock.state == ClockState.BREACHED:
            escalations.append(EscalationReason.BREACHED)

    findings, too_many = inspect_attachments(getattr(dispute, "attachments", None) or (), cfg)
    unreadable = [f.attachment_id for f in findings if not f.readable]
    if unreadable:
        errors.append("attachments unreadable: " + ", ".join(unreadable))
    if too_many:
        errors.append(f"too many attachments: {len(findings)} > {cfg.max_attachments_per_case}")
    if unreadable or too_many:
        escalations.append(EscalationReason.DOC_UNREADABLE)

    repeat_of = None
    received = parse_iso_date(getattr(dispute, "date_received", None))
    if received is not None and prior_cases:
        hit = find_repeat(date_received=received, categories=code_categories(dispute.dispute_codes),
                          prior_cases=prior_cases, window_days=cfg.repeat_window_days)
        if hit is not None:
            repeat_of = str(hit.get("case_id")) if hit.get("case_id") is not None else None

    deduped = tuple(dict.fromkeys(escalations))
    result = IntakeResult(
        valid=EscalationReason.INTAKE_INVALID not in deduped,
        escalations=deduped,
        clock=clock,
        attachment_findings=findings,
        duplicate_of_case_id=None,
        repeat_of_case_id=repeat_of,
        errors=tuple(errors),
    )
    return result, detect(dispute, findings, llm_flag=llm_flag)
