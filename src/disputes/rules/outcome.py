"""R-10 outcome rules, R-29 explainability. OWNER: rules agent.

Precedence: any escalation condition > MODIFY > VERIFY. All triggered reasons are recorded
as RuleFirings (rule ID + version + evidence IDs). The system never proposes DELETE.
INVARIANT (B1, ≥10,000 property tests): VERIFIED_AS_REPORTED ⇒ every month MATCH ∧ no
escalation ∧ every claim CONTRADICTED ∧ categories == {PAYMENT_HISTORY}.

Rules v1.0.0, in evaluation order (all are evaluated; nothing short-circuits the record):
  U   upstream_escalations ∪ classification.escalations -> recorded as-is (force ESCALATED).
  S   scope guard (R-06/R-07): route ESCALATE_* -> its reason; categories with IDENTITY_FRAUD
      -> ID_FRAUD_SUSPECTED; >1 real category -> MULTI_ISSUE; UNCERTAIN or empty -> CLASS_CONFLICT;
      route inconsistent with categories (INVESTIGATE without exactly {PAYMENT_HISTORY}, or
      OUT_OF_SCOPE with exactly {PAYMENT_HISTORY}) -> CLASS_CONFLICT (fail safe).
      A single non-PH category routed OUT_OF_SCOPE with no escalation -> OUT_OF_SCOPE.
  The month and note rules below run only when categories == {PAYMENT_HISTORY} (the only
  investigated category); otherwise the comparisons are recorded as notes, not reasons.
  M1  no comparisons -> MONTHS_UNDETERMINED (R-08).
  M2  any NO_DATA -> EVIDENCE_MISSING.
  C1  cycle evidence with several SoR rows for a disputed month -> EVIDENCE_CONFLICT.
  C2  HARDSHIP/DEFERRAL/FORBEARANCE note overlapping a disputed month -> EVIDENCE_CONFLICT.
      Overlap: closed date interval [start_date, end_date] intersects the disputed calendar
      month [first day, last day]. Missing end_date = open-ended. Missing/unparseable
      start_date or end_date, or an unknown note type -> treated as overlapping (fail safe).
  C3  llm_note_flag -> EVIDENCE_CONFLICT (a free-text note can only add an escalation).
  K1  when otherwise VERIFY (no reason so far and no MISMATCH): any claim not validly
      CONTRADICTED -> CLAIM_UNRESOLVED. "Validly" = finding CONTRADICTED and ≥1 evidence ID that
      exists in the evidence list; finding None counts as unresolved.
  O   reasons -> ESCALATED (no corrections); else any MISMATCH -> MODIFY with one Correction per
      mismatched month; else VERIFIED_AS_REPORTED. DELETE is never produced.
"""
from __future__ import annotations

from calendar import monthrange
from datetime import date

from disputes import reference
from disputes.domain import (Category, Claim, ClaimFinding, Classification, Correction, Decision,
                             EscalationReason, Evidence, MonthComparison, MonthResult, NoteType,
                             Outcome, Route, RuleFiring)
from disputes.rules.compare import RATING_TABLE
from disputes.rules.evidence import valid_month

RULES_VERSION = "1.0.0"

CONFLICT_NOTE_TYPES = frozenset({NoteType.HARDSHIP, NoteType.DEFERRAL, NoteType.FORBEARANCE})
PH_ONLY = frozenset({Category.PAYMENT_HISTORY})
_REASON_ORDER = {r: i for i, r in enumerate(EscalationReason)}

# Requirement that raises each reason upstream (for R-29 rule IDs of upstream escalations).
UPSTREAM_ORIGIN = {
    EscalationReason.INTAKE_INVALID: "R-02", EscalationReason.DOC_UNREADABLE: "R-03",
    EscalationReason.BREACHED: "R-05", EscalationReason.CLASS_CONFLICT: "R-07",
    EscalationReason.ID_FRAUD_SUSPECTED: "R-07", EscalationReason.MULTI_ISSUE: "R-07",
    EscalationReason.MONTHS_UNDETERMINED: "R-08", EscalationReason.EVIDENCE_MISSING: "R-10",
    EscalationReason.EVIDENCE_CONFLICT: "R-10", EscalationReason.CLAIM_UNRESOLVED: "R-10",
    EscalationReason.QUOTE_UNLOCATED: "R-11", EscalationReason.UNADDRESSED_CLAIM: "R-11",
    EscalationReason.DRAFT_INVALID: "R-13", EscalationReason.LLM_UNAVAILABLE: "R-15",
    EscalationReason.SYSTEM_ERROR: "R-15",
}
ROUTE_REASON = {
    Route.ESCALATE_FRAUD: EscalationReason.ID_FRAUD_SUSPECTED,
    Route.ESCALATE_MULTI_ISSUE: EscalationReason.MULTI_ISSUE,
    Route.ESCALATE_CLASS_CONFLICT: EscalationReason.CLASS_CONFLICT,
}


def _month_bounds(m: str) -> tuple[date, date]:
    y, mo = int(m[:4]), int(m[5:7])
    return date(y, mo, 1), date(y, mo, monthrange(y, mo)[1])


def _parse_date(v) -> date | None:
    if not isinstance(v, str):
        return None
    try:
        return date.fromisoformat(v)
    except ValueError:
        return None


def note_overlaps(note: dict, month: str) -> tuple[bool, str]:
    """(overlaps, why). Closed-interval overlap of the note with the calendar month; fail safe
    (True) when the note's dates cannot be read. `month` must be YYYY-MM."""
    s, e = _month_bounds(month)
    start = _parse_date(note.get("start_date"))
    if start is None:
        return True, "note start_date missing or unparseable (fail safe)"
    end_raw = note.get("end_date")
    if end_raw is None:
        return start <= e, "open-ended note (no end_date)"
    end = _parse_date(end_raw)
    if end is None:
        return True, "note end_date unparseable (fail safe)"
    if end < start:
        return True, "note end_date before start_date (fail safe)"
    return start <= e and end >= s, f"{start.isoformat()}..{end.isoformat()} vs {month}"


def note_is_conflict_type(note: dict) -> tuple[bool, str]:
    t = note.get("type")
    if t not in {x.value for x in NoteType}:
        return True, f"unknown note type {t!r} (fail safe)"
    return NoteType(t) in CONFLICT_NOTE_TYPES, str(t)


class _Acc:
    def __init__(self, known: set[str]):
        self.known = known
        self.reasons: list[EscalationReason] = []
        self.firings: list[RuleFiring] = []

    def escalate(self, reason: EscalationReason, rule_id: str, evidence_ids=(), detail: str = ""):
        if reason not in self.reasons:
            self.reasons.append(reason)
        self.fire(rule_id, reason.value, evidence_ids, detail)

    def fire(self, rule_id: str, result: str, evidence_ids=(), detail: str = ""):
        ids = tuple(dict.fromkeys(i for i in evidence_ids if i in self.known))  # cite only real evidence
        self.firings.append(RuleFiring(rule_id, RULES_VERSION, result, ids, detail))


def claim_is_valid_contradiction(c: Claim, known_ids: set[str]) -> bool:
    return (c.finding == ClaimFinding.CONTRADICTED and bool(c.evidence_ids)
            and all(i in known_ids for i in c.evidence_ids))


def decide(*, classification: Classification, comparisons: list[MonthComparison], evidence: list[Evidence],
           claims: list[Claim], upstream_escalations: tuple[EscalationReason, ...] = (),
           llm_note_flag: bool = False) -> Decision:
    """Inputs are everything known about the case so far; `upstream_escalations` carries
    reasons raised by intake / classification / claims / drafting (they force ESCALATED).
    - any NO_DATA -> EVIDENCE_MISSING
    - HARDSHIP/DEFERRAL/FORBEARANCE note overlapping a disputed month, or llm_note_flag -> EVIDENCE_CONFLICT
    - any claim SUPPORTED or NOT_ADDRESSABLE (when otherwise VERIFY) -> CLAIM_UNRESOLVED
    - any MISMATCH and no escalation -> MODIFY with a Correction per mismatched month
    - else VERIFIED_AS_REPORTED
    See the module docstring for the exact rule list.
    """
    by_id = {e.evidence_id: e for e in evidence}
    known = set(by_id)
    acc = _Acc(known)
    acdv = ("EV-ACDV",) if "EV-ACDV" in known else ()
    att_ids = tuple(i for i in sorted(known) if i.startswith("EV-ATT-"))

    # U: upstream reasons
    for r in tuple(upstream_escalations) + tuple(classification.escalations):
        r = EscalationReason(r)
        if r in acc.reasons:
            continue
        cite = acdv + (att_ids if r == EscalationReason.DOC_UNREADABLE else ())
        acc.escalate(r, f"{UPSTREAM_ORIGIN[r]}.{r.value}", cite, "raised upstream; recorded by R-10")

    # S: scope guard
    cats = frozenset(Category(c) for c in classification.categories)
    route = Route(classification.route)
    if route in ROUTE_REASON:
        acc.escalate(ROUTE_REASON[route], f"R-07.ROUTE.{route.value}", acdv, f"route {route.value}")
    real = cats - {Category.UNCERTAIN}
    if Category.IDENTITY_FRAUD in cats:
        acc.escalate(EscalationReason.ID_FRAUD_SUSPECTED, "R-10.SCOPE.ID_FRAUD", acdv, "IDENTITY_FRAUD in categories")
    if len(real) > 1:
        acc.escalate(EscalationReason.MULTI_ISSUE, "R-10.SCOPE.MULTI_ISSUE", acdv,
                     "categories " + ",".join(sorted(real)))
    if not real or Category.UNCERTAIN in cats:
        acc.escalate(EscalationReason.CLASS_CONFLICT, "R-10.SCOPE.UNCERTAIN", acdv, "category undetermined")
    if (route == Route.INVESTIGATE) != (cats == PH_ONLY):
        acc.escalate(EscalationReason.CLASS_CONFLICT, "R-10.SCOPE.ROUTE_INCONSISTENT", acdv,
                     f"route {route.value} inconsistent with categories {sorted(cats)}")

    in_scope = cats == PH_ONLY
    mismatches = [c for c in comparisons if c.result == MonthResult.MISMATCH]

    if in_scope:
        months = sorted({c.month for c in comparisons})
        # M1
        if not comparisons:
            acc.escalate(EscalationReason.MONTHS_UNDETERMINED, "R-08.MONTHS_UNDETERMINED", acdv,
                         "no disputed month in the ACDV or the claims")
        # M2
        nodata = [c for c in comparisons if c.result == MonthResult.NO_DATA]
        if nodata:
            acc.escalate(EscalationReason.EVIDENCE_MISSING, "R-10.EVIDENCE_MISSING",
                         [i for c in nodata for i in c.evidence_ids] or acdv,
                         "NO_DATA for " + ",".join(c.month for c in nodata))
        # C1
        for m in months:
            ev = by_id.get(f"EV-CYCLE-{m}")
            if ev is not None and "conflicting_rows" in ev.content:
                acc.escalate(EscalationReason.EVIDENCE_CONFLICT, "R-10.EVIDENCE_CONFLICT.CYCLE_ROWS",
                             (ev.evidence_id,), f"{len(ev.content['conflicting_rows'])} SoR cycle rows for {m}")
        # C2
        valid_months = [m for m in months if valid_month(m)]
        for ev in sorted((e for e in evidence if e.kind == "note"), key=lambda e: e.evidence_id):
            is_type, why_type = note_is_conflict_type(ev.content)
            if not is_type:
                continue
            for m in valid_months:
                hit, why = note_overlaps(ev.content, m)
                if hit:
                    acc.escalate(EscalationReason.EVIDENCE_CONFLICT, "R-10.EVIDENCE_CONFLICT.NOTE",
                                 (ev.evidence_id,) + ((f"EV-CYCLE-{m}",) if f"EV-CYCLE-{m}" in known else ()),
                                 f"{why_type} note overlaps disputed month {m}: {why}")
        # C3
        if llm_note_flag:
            acc.escalate(EscalationReason.EVIDENCE_CONFLICT, "R-10.EVIDENCE_CONFLICT.LLM_NOTE_FLAG",
                         [e.evidence_id for e in evidence if e.kind == "free_text_note"] or acdv,
                         "LLM flagged a free-text note as conflicting")
        # K1
        unresolved = [c for c in claims if not claim_is_valid_contradiction(c, known)]
        if unresolved and not acc.reasons and not mismatches:
            acc.escalate(EscalationReason.CLAIM_UNRESOLVED, "R-10.CLAIM_UNRESOLVED",
                         [i for c in unresolved for i in c.evidence_ids if i in known] or acdv,
                         "; ".join(f"{c.claim_id}={c.finding.value if c.finding else 'NONE'}" for c in unresolved))
        elif unresolved:
            acc.fire("R-10.CLAIM_NOT_CONTRADICTED", "NOTE",
                     [i for c in unresolved for i in c.evidence_ids if i in known],
                     "not escalated as CLAIM_UNRESOLVED because the case is already escalated or MODIFY: "
                     + "; ".join(f"{c.claim_id}={c.finding.value if c.finding else 'NONE'}" for c in unresolved))
    elif comparisons:
        acc.fire("R-10.SCOPE.NOT_INVESTIGATED", "NOTE", [i for c in comparisons for i in c.evidence_ids],
                 "month comparisons present but categories are not exactly {PAYMENT_HISTORY}; not evaluated")

    reasons = tuple(sorted(acc.reasons, key=_REASON_ORDER.__getitem__))
    corrections: tuple[Correction, ...] = ()
    if reasons:
        outcome = Outcome.ESCALATED
        if in_scope:
            for c in mismatches:   # "mismatch shown, no outcome proposed" (PRD §6 acceptance)
                acc.fire("R-09.MISMATCH", "NOTE", c.evidence_ids,
                         f"{c.month}: reported {c.reported_rating}, expected {c.expected_rating} (not proposed: escalated)")
        acc.fire("R-10.OUTCOME", outcome.value, [i for f in acc.firings for i in f.evidence_ids],
                 "precedence: escalation > MODIFY > VERIFY; reasons " + ",".join(r.value for r in reasons))
    elif not in_scope:
        outcome = Outcome.OUT_OF_SCOPE
        acc.fire("R-10.OUTCOME", outcome.value, acdv, f"categories {sorted(cats)} routed OUT_OF_SCOPE")
    elif mismatches:
        outcome = Outcome.MODIFY
        corrections = tuple(Correction(c.month, "payment_rating", c.reported_rating, c.expected_rating)
                            for c in sorted(mismatches, key=lambda c: c.month))
        acc.fire("R-10.OUTCOME", outcome.value, [i for c in mismatches for i in c.evidence_ids],
                 "; ".join(f"{x.month}: {x.reported} -> {x.corrected}" for x in corrections))
    else:
        outcome = Outcome.VERIFIED_AS_REPORTED
        acc.fire("R-10.OUTCOME", outcome.value,
                 [i for c in comparisons for i in c.evidence_ids] + [i for c in claims for i in c.evidence_ids],
                 f"all {len(comparisons)} month(s) MATCH, {len(claims)} claim(s) CONTRADICTED, no escalation")

    if outcome == Outcome.DELETE:  # R-10: never proposed by the system (unreachable; kept under -O)
        raise RuntimeError("R-10 violation: system proposed DELETE")
    return Decision(outcome=outcome, escalation_reasons=reasons, corrections=corrections,
                    firings=tuple(acc.firings), rules_version=RULES_VERSION,
                    table_versions=reference.versions(RATING_TABLE))
