"""R-17 reviewer actions, R-19 second approval, R-20 package. OWNER: web agent.

Testable service layer: the HTTP routes are thin wrappers around these functions.

Rules enforced here (PRD §6, Appendix C):
- Only SPECIALIST / SUPERVISOR / ADMIN act on cases; AUDITOR and CLIENT_VIEWER are read-only.
- Every EDIT, MARK_OUT_OF_SCOPE and any DELETE needs a reason code (Appendix C) and >= 10 chars of
  text; ESCALATE and REJECT_SECOND_APPROVAL need >= 10 chars of text. An APPROVE of a working
  decision that departs from the proposal is only reachable through an EDIT, which carried the reason.
- APPROVE is blocked until every claim lacking a valid finding has a human finding (evidence ID or
  reason), and, when the validator failed (or the outcome/corrections changed), until the reviewer
  has written the narrative (sentences marked source=HUMAN).
- DELETE or HIGH suspicion -> AWAITING_SECOND_APPROVAL; a different SUPERVISOR who has not approved
  or edited the case gives the second approval (R-18 separation of duties).
- Final approval builds an immutable package -> ResponseSink stub + `package` artifact; the case goes
  APPROVED -> SUBMITTED_STUB. Reopening a submitted case needs a reason; the next approval writes
  package version n+1 with that reason and the hash of the version it supersedes.
- State changes only through workflow.state_machine.transition. Each action writes a `review`
  artifact and a REVIEW_ACTION audit event in the same transaction as the state change.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from disputes.audit.chain import append_event, canonical, sha256_hex
from disputes.config import Config
from disputes.db import repo
from disputes.domain import ActorType, ArtifactKind, CaseState as S, Outcome, ReviewAction, Role, SuspicionLevel
from disputes.web import casedata as cd
from disputes.web import metrics
from disputes.workflow.state_machine import transition

REASON_CODES = ("EVIDENCE_MISREAD", "ADDITIONAL_EVIDENCE_OUTSIDE_SYSTEM", "HARDSHIP_OR_DEFERRAL_POLICY",
                "CONSUMER_DOC_PERSUASIVE", "DATA_UNVERIFIABLE", "CLASSIFICATION_WRONG", "CLAIM_FINDING_ENTERED",
                "NARRATIVE_EDIT_ONLY", "OTHER")
ACTING_ROLES = frozenset({Role.SPECIALIST, Role.SUPERVISOR, Role.ADMIN})
REOPEN = "REOPEN_AFTER_SUBMISSION"           # not in domain.ReviewAction; see notes (contract request)
_MONTH = re.compile(r"^\d{4}-(0[1-9]|1[0-2])$")


class ActionError(ValueError):
    """A rule blocked the action. `field` names the missing/invalid input when there is one."""

    def __init__(self, message: str, field: str | None = None):
        super().__init__(message)
        self.field = field


class ActionForbidden(PermissionError):
    pass


class StaleCase(RuntimeError):
    pass


@dataclass(frozen=True)
class Actor:
    user_id: str
    role: Role
    display_name: str

    @classmethod
    def of(cls, principal) -> "Actor":
        return cls(principal.user_id, Role(principal.role), principal.display_name)


# ---------------------------------------------------------------- helpers
def _require_actor(actor: Actor, roles=ACTING_ROLES) -> None:
    if actor.role not in roles:
        raise ActionForbidden(f"{actor.role} cannot take this action")


def _require_state(case: dict, *states: S) -> None:
    if case["state"] not in {s.value for s in states}:
        raise ActionError(f"case is {case['state']}; this action needs " + " or ".join(s.value for s in states),
                          field="state")


def _check_reason(reason_code: str | None, reason_text: str | None, *, code_required: bool = True) -> None:
    if code_required and not reason_code:
        raise ActionError("reason_code is required (PRD Appendix C)", field="reason_code")
    if reason_code and reason_code not in REASON_CODES:
        raise ActionError(f"reason_code {reason_code!r} is not in PRD Appendix C", field="reason_code")
    if len((reason_text or "").strip()) < cd.MIN_REASON_CHARS:
        raise ActionError(f"reason_text must be at least {cd.MIN_REASON_CHARS} characters", field="reason_text")


def _lock(conn, tenant_id: str, case_id: str, expected_version: int | None) -> dict:
    case = repo.get_case(conn, tenant_id=tenant_id, case_id=case_id, for_update=True)
    if expected_version is not None and case["version"] != expected_version:
        raise StaleCase(f"{case_id} changed since you opened it (version {case['version']}, "
                        f"you had {expected_version}); reload and try again")
    return case


def _move(conn, case: dict, to: S, actor: Actor, reason: str | None = None) -> dict:
    return transition(conn, tenant_id=case["tenant_id"], case_id=case["case_id"], to=to,
                      actor_type=ActorType.HUMAN, actor_id=actor.user_id, actor_role=actor.role, reason=reason)


def _review(conn, case: dict, actor: Actor, action: str, *, from_state: str, to_state: str,
            reason_code: str | None = None, reason_text: str | None = None, working: dict | None = None,
            extra: dict | None = None) -> dict:
    rec = {"action": action, "actor_id": actor.user_id, "actor_role": actor.role.value,
           "actor_name": actor.display_name, "reason_code": reason_code,
           "reason_text": (reason_text or "").strip() or None, "from_state": from_state, "to_state": to_state,
           **({"working": working} if working is not None else {}), **(extra or {})}
    art = repo.put_artifact(conn, tenant_id=case["tenant_id"], case_id=case["case_id"], kind=ArtifactKind.REVIEW,
                            data=rec, created_by=actor.user_id)
    append_event(conn, tenant_id=case["tenant_id"], case_id=case["case_id"], event_type="REVIEW_ACTION",
                 actor_type=ActorType.HUMAN, actor_id=actor.user_id, actor_role=actor.role.value,
                 payload={**rec, "review_version": art["version"], "review_sha256": art["data_sha256"]})
    return rec


def _decided(conn, case: dict, actor: Actor, action: str, *, override: bool, reason_code: str | None) -> None:
    secs = metrics.seconds_since_first_view(conn, tenant_id=case["tenant_id"], case_id=case["case_id"])
    metrics.record(conn, tenant_id=case["tenant_id"], case_id=case["case_id"], user_id=actor.user_id,
                   metric="decided", value=secs,
                   detail={"action": action, "override": override, "reason_code": reason_code,
                           "escalation_reasons": list(case.get("escalation_reasons") or [])})


def _bump(conn, case: dict, **fields) -> dict:
    """Bump the case version (optimistic concurrency) and set allowed fields."""
    return repo.update_case_fields(conn, tenant_id=case["tenant_id"], case_id=case["case_id"],
                                   **(fields or {"assigned_to": case.get("assigned_to")}))


def _actors_who(b: cd.CaseBundle, *actions: str) -> set[str]:
    return {r["data"]["actor_id"] for r in b.reviews if r["data"].get("action") in actions}


# ---------------------------------------------------------------- open / take
def open_case(conn, *, tenant_id: str, case_id: str, actor: Actor) -> dict:
    """A reviewer opening a DRAFT_READY case moves it to IN_REVIEW (and is assigned). Records R-24
    opened/first_viewed for acting staff and the R-21 CASE_READ for AUDITOR/ADMIN."""
    with conn.transaction():
        case = repo.get_case(conn, tenant_id=tenant_id, case_id=case_id, for_update=True)
        if actor.role in ACTING_ROLES:
            if case["state"] == S.DRAFT_READY.value:
                case = _move(conn, case, S.IN_REVIEW, actor, reason="opened by reviewer")
                if not case.get("assigned_to"):
                    case = _bump(conn, case, assigned_to=actor.user_id)
            metrics.record_open(conn, tenant_id=tenant_id, case_id=case_id, user_id=actor.user_id)
    metrics.record_case_read(conn, tenant_id=tenant_id, case_id=case_id, user_id=actor.user_id,
                             role=actor.role.value, surface="ops_case_view")
    return case


def take_for_review(conn, *, tenant_id: str, case_id: str, actor: Actor, expected_version: int | None = None) -> dict:
    """ESCALATED -> IN_REVIEW is supervisor-only (PRD §6)."""
    _require_actor(actor, {Role.SUPERVISOR, Role.ADMIN})
    with conn.transaction():
        case = _lock(conn, tenant_id, case_id, expected_version)
        _require_state(case, S.ESCALATED)
        new = _move(conn, case, S.IN_REVIEW, actor, reason="supervisor took escalated case for review")
        return _bump(conn, new, assigned_to=actor.user_id)


# ---------------------------------------------------------------- EDIT
def _clean_corrections(corrections) -> list[dict]:
    out = []
    for i, c in enumerate(corrections or []):
        month, corrected = str(c.get("month") or "").strip(), str(c.get("corrected") or "").strip()
        if not _MONTH.match(month):
            raise ActionError(f"correction {i + 1}: month must be YYYY-MM", field="corrections")
        if not corrected:
            raise ActionError(f"correction {i + 1}: corrected value is required", field="corrections")
        out.append({"month": month, "field": c.get("field") or "payment_rating",
                    "reported": c.get("reported"), "corrected": corrected})
    return out


def edit(conn, *, tenant_id: str, case_id: str, actor: Actor, reason_code: str | None, reason_text: str | None,
         outcome: str | None = None, corrections: list[dict] | None = None, narrative: str | None = None,
         claim_findings: dict[str, dict] | None = None, cfg: Config | None = None,
         expected_version: int | None = None) -> dict:
    """Change the working decision (outcome, corrected fields, narrative, claim findings). The case
    stays IN_REVIEW; approval is a separate action. Returns the new working state."""
    cfg = cfg or Config()
    _require_actor(actor)
    _check_reason(reason_code, reason_text)
    with conn.transaction():
        case = _lock(conn, tenant_id, case_id, expected_version)
        _require_state(case, S.IN_REVIEW)
        b = cd.load_bundle(conn, tenant_id=tenant_id, case_id=case_id, case=case)
        w = dict(cd.working_state(b))
        changes = []
        if outcome is not None and outcome != w["outcome"]:
            if outcome not in cd.APPROVABLE_OUTCOMES:
                raise ActionError("outcome must be VERIFIED_AS_REPORTED, MODIFY or DELETE "
                                  "(use Escalate or Mark out of scope otherwise)", field="outcome")
            w["outcome"] = outcome
            changes.append("outcome")
        if corrections is not None:
            cc = _clean_corrections(corrections)
            if cd._norm_corr(cc) != cd._norm_corr(w["corrections"]):
                w["corrections"] = cc
                changes.append("corrections")
        if w["outcome"] != Outcome.MODIFY.value and w["corrections"]:
            w["corrections"] = []
        if claim_findings:
            known = {c["claim_id"] for c in b.claims}
            merged = dict(w.get("claim_findings") or {})
            for cid, f in claim_findings.items():
                if cid not in known:
                    raise ActionError(f"unknown claim {cid}", field="claim_findings")
                f = {"finding": f.get("finding"), "evidence_ids": [x for x in (f.get("evidence_ids") or []) if x],
                     "reason": (f.get("reason") or "").strip()}
                err = cd.human_finding_error(f, b.evidence_ids)
                if err:
                    raise ActionError(f"claim {cid}: {err}", field="claim_findings")
                merged[cid] = {**f, "entered_by": actor.user_id}
            w["claim_findings"] = merged
            changes.append("claim_findings")
        new_draft = None
        if narrative is not None and narrative.strip():
            sents = cd.human_sentences(narrative)
            if cd.word_count(sents) > cfg.narrative_max_words:
                raise ActionError(f"narrative is {cd.word_count(sents)} words; the limit is "
                                  f"{cfg.narrative_max_words}", field="narrative")
            if sents != w.get("narrative"):
                w["narrative"] = sents
                changes.append("narrative")
                new_draft = {"sentences": sents, "validator_errors": [], "attempts": 0, "valid": True,
                             "template_library_version": "", "human_authored": True}
        if not changes:
            raise ActionError("nothing changed: edit the outcome, corrected fields, narrative or a claim finding")
        if w["outcome"] == Outcome.MODIFY.value and not w["corrections"]:
            raise ActionError("a Modify outcome needs at least one corrected field", field="corrections")
        if new_draft is not None:
            repo.put_artifact(conn, tenant_id=tenant_id, case_id=case_id, kind=ArtifactKind.DRAFT,
                              data=new_draft, created_by=actor.user_id)
        _review(conn, case, actor, ReviewAction.EDIT.value, from_state=case["state"], to_state=case["state"],
                reason_code=reason_code, reason_text=reason_text, working=w, extra={"changed": changes})
        _bump(conn, case)
        return w


# ---------------------------------------------------------------- APPROVE (first)
def approve(conn, *, tenant_id: str, case_id: str, actor: Actor, sink, cfg: Config | None = None,
            expected_version: int | None = None) -> dict:
    """Approve the working decision. Returns the updated case row."""
    cfg = cfg or Config()
    _require_actor(actor)
    with conn.transaction():
        case = _lock(conn, tenant_id, case_id, expected_version)
        _require_state(case, S.IN_REVIEW)
        b = cd.load_bundle(conn, tenant_id=tenant_id, case_id=case_id, case=case)
        w = cd.working_state(b)
        blockers = cd.approval_blockers(b, narrative_max_words=cfg.narrative_max_words, w=w)
        if blockers:
            raise ActionError("Approval is blocked. " + " ".join(blockers), field="approval")
        departs = cd.departs_from_proposal(b, w)
        if departs and not any(r["data"].get("action") == ReviewAction.EDIT.value and r["data"].get("reason_code")
                               for r in b.reviews):
            raise ActionError("a departure from the proposal needs a reason code (use Edit)", field="reason_code")
        last_reason = _last_edit_reason(b)
        needs_second = (w["outcome"] == Outcome.DELETE.value
                        or case.get("suspicion_level") == SuspicionLevel.HIGH.value)
        if needs_second:
            why = "DELETE outcome" if w["outcome"] == Outcome.DELETE.value else "HIGH suspicious-content flag"
            new = _move(conn, case, S.AWAITING_SECOND_APPROVAL, actor, reason=f"R-19 second approval: {why}")
            _review(conn, case, actor, ReviewAction.APPROVE.value, from_state=case["state"], to_state=new["state"],
                    working=w, extra={"stage": "first", "second_approval_required": why,
                                      "departs_from_proposal": departs})
            _decided(conn, case, actor, ReviewAction.APPROVE.value, override=departs, reason_code=last_reason)
            return _bump(conn, new)
        new = _move(conn, case, S.APPROVED, actor, reason="approved")
        _review(conn, case, actor, ReviewAction.APPROVE.value, from_state=case["state"], to_state=S.APPROVED.value,
                working=w, extra={"stage": "final", "departs_from_proposal": departs})
        _decided(conn, case, actor, ReviewAction.APPROVE.value, override=departs, reason_code=last_reason)
        b = cd.load_bundle(conn, tenant_id=tenant_id, case_id=case_id, case=new)
        return _finalise(conn, b, w, approvals=[_approval(actor)], authorised_by=actor, sink=sink)


def _approval(actor: Actor, stage: str = "final") -> dict:
    return {"user_id": actor.user_id, "role": actor.role.value, "display_name": actor.display_name, "stage": stage}


def _last_edit_reason(b: cd.CaseBundle) -> str | None:
    for r in reversed(b.reviews):
        if r["data"].get("action") in (ReviewAction.EDIT.value, REOPEN):
            return r["data"].get("reason_code")
    return None


# ---------------------------------------------------------------- SECOND APPROVAL (R-19)
def second_approve(conn, *, tenant_id: str, case_id: str, actor: Actor, sink, cfg: Config | None = None,
                   expected_version: int | None = None) -> dict:
    _require_actor(actor, {Role.SUPERVISOR})
    with conn.transaction():
        case = _lock(conn, tenant_id, case_id, expected_version)
        _require_state(case, S.AWAITING_SECOND_APPROVAL)
        b = cd.load_bundle(conn, tenant_id=tenant_id, case_id=case_id, case=case)
        _separation_of_duties(b, actor)
        first = next(r["data"] for r in reversed(b.reviews) if r["data"].get("action") == ReviewAction.APPROVE.value)
        w = cd.working_state(b)
        new = _move(conn, case, S.APPROVED, actor, reason="R-19 second approval given")
        _review(conn, case, actor, ReviewAction.SECOND_APPROVE.value, from_state=case["state"],
                to_state=S.APPROVED.value, extra={"first_approver": first["actor_id"]})
        _decided(conn, case, actor, ReviewAction.SECOND_APPROVE.value, override=cd.departs_from_proposal(b, w),
                 reason_code=_last_edit_reason(b))
        b = cd.load_bundle(conn, tenant_id=tenant_id, case_id=case_id, case=new)
        approvals = [{"user_id": first["actor_id"], "role": first["actor_role"], "display_name": first["actor_name"],
                      "stage": "first"}, _approval(actor, "second")]
        return _finalise(conn, b, w, approvals=approvals, authorised_by=actor, sink=sink)


def reject_second_approval(conn, *, tenant_id: str, case_id: str, actor: Actor, reason_text: str,
                           reason_code: str | None = None, expected_version: int | None = None) -> dict:
    _require_actor(actor, {Role.SUPERVISOR})
    _check_reason(reason_code, reason_text, code_required=False)
    with conn.transaction():
        case = _lock(conn, tenant_id, case_id, expected_version)
        _require_state(case, S.AWAITING_SECOND_APPROVAL)
        b = cd.load_bundle(conn, tenant_id=tenant_id, case_id=case_id, case=case)
        _separation_of_duties(b, actor)
        new = _move(conn, case, S.IN_REVIEW, actor, reason="second approval rejected")
        _review(conn, case, actor, ReviewAction.REJECT_SECOND_APPROVAL.value, from_state=case["state"],
                to_state=new["state"], reason_code=reason_code, reason_text=reason_text)
        return _bump(conn, new)


def _separation_of_duties(b: cd.CaseBundle, actor: Actor) -> None:
    if actor.user_id in _actors_who(b, ReviewAction.APPROVE.value, ReviewAction.EDIT.value):
        raise ActionForbidden("separation of duties (R-18): you approved or edited this case, so a different "
                              "supervisor must give the second approval")


# ---------------------------------------------------------------- ESCALATE / OUT OF SCOPE / REOPEN
def escalate(conn, *, tenant_id: str, case_id: str, actor: Actor, reason_text: str,
             reason_code: str | None = None, expected_version: int | None = None) -> dict:
    _require_actor(actor)
    _check_reason(reason_code, reason_text, code_required=False)
    with conn.transaction():
        case = _lock(conn, tenant_id, case_id, expected_version)
        _require_state(case, S.DRAFT_READY, S.IN_REVIEW, S.AWAITING_SECOND_APPROVAL, S.APPROVED)
        new = _move(conn, case, S.ESCALATED, actor, reason=reason_text.strip())
        _review(conn, case, actor, ReviewAction.ESCALATE.value, from_state=case["state"], to_state=new["state"],
                reason_code=reason_code, reason_text=reason_text)
        _decided(conn, case, actor, ReviewAction.ESCALATE.value, override=True, reason_code=reason_code)
        return _bump(conn, new)


def mark_out_of_scope(conn, *, tenant_id: str, case_id: str, actor: Actor, reason_code: str, reason_text: str,
                      expected_version: int | None = None) -> dict:
    """IN_REVIEW -> OUT_OF_SCOPE (any acting staff); ESCALATED -> OUT_OF_SCOPE (supervisor, state machine)."""
    _require_actor(actor)
    _check_reason(reason_code, reason_text)
    with conn.transaction():
        case = _lock(conn, tenant_id, case_id, expected_version)
        _require_state(case, S.IN_REVIEW, S.ESCALATED)
        try:
            new = _move(conn, case, S.OUT_OF_SCOPE, actor, reason=reason_text.strip())
        except PermissionError as e:
            raise ActionForbidden(str(e)) from e
        _review(conn, case, actor, ReviewAction.MARK_OUT_OF_SCOPE.value, from_state=case["state"],
                to_state=new["state"], reason_code=reason_code, reason_text=reason_text)
        _decided(conn, case, actor, ReviewAction.MARK_OUT_OF_SCOPE.value,
                 override=case.get("proposed_outcome") != Outcome.OUT_OF_SCOPE.value, reason_code=reason_code)
        return _bump(conn, new, final_outcome=Outcome.OUT_OF_SCOPE.value)


def reopen_submitted(conn, *, tenant_id: str, case_id: str, actor: Actor, reason_code: str, reason_text: str,
                     expected_version: int | None = None) -> dict:
    """R-20: a change after submission. SUBMITTED_STUB -> IN_REVIEW; the next approval writes a new
    package version carrying this reason. Supervisor or admin only."""
    _require_actor(actor, {Role.SUPERVISOR, Role.ADMIN})
    _check_reason(reason_code, reason_text)
    with conn.transaction():
        case = _lock(conn, tenant_id, case_id, expected_version)
        _require_state(case, S.SUBMITTED_STUB)
        new = _move(conn, case, S.IN_REVIEW, actor, reason=f"post-submission change: {reason_text.strip()}")
        b = cd.load_bundle(conn, tenant_id=tenant_id, case_id=case_id, case=case)
        _review(conn, case, actor, REOPEN, from_state=case["state"], to_state=new["state"],
                reason_code=reason_code, reason_text=reason_text, working=cd.working_state(b),
                extra={"package_version_reopened": len(b.packages)})
        return _bump(conn, new, final_outcome=None)


# ---------------------------------------------------------------- package (R-20)
def _finalise(conn, b: cd.CaseBundle, w: dict, *, approvals: list[dict], authorised_by: Actor, sink) -> dict:
    case = b.case
    prev = b.packages[-1] if b.packages else None
    change_reason = None
    if prev is not None:
        reopen = next((r["data"] for r in reversed(b.reviews) if r["data"].get("action") == REOPEN), None)
        change_reason = {"reason_code": (reopen or {}).get("reason_code"),
                         "reason_text": (reopen or {}).get("reason_text"),
                         "reopened_by": (reopen or {}).get("actor_id")}
    sents = cd.narrative_sentences(b, w)
    dispute = b.get(ArtifactKind.DISPUTE) or {}
    pkg = {
        "package_version": len(b.packages) + 1,
        "tenant_id": case["tenant_id"], "case_id": case["case_id"], "channel": case["channel"],
        "control_number": case["control_number"], "cra": case["cra"], "account_number": case["account_number"],
        "outcome": w["outcome"], "corrections": w["corrections"],
        "narrative": " ".join(s["text"] for s in sents), "narrative_sentences": sents,
        "dfAuthorizedName": authorised_by.display_name,
        "approvals": approvals,
        "versions": cd.versions_for_case(conn, b),
        "supersedes_package_sha256": prev["data_sha256"] if prev else None,
        "change_reason": change_reason,
        "synthetic": bool(case.get("synthetic", True)) and bool(dispute.get("synthetic", True)),
    }
    receipt = sink.write_package(pkg)
    art = repo.put_artifact(conn, tenant_id=case["tenant_id"], case_id=case["case_id"], kind=ArtifactKind.PACKAGE,
                            data={**pkg, "sink_receipt": receipt}, created_by=authorised_by.user_id)
    append_event(conn, tenant_id=case["tenant_id"], case_id=case["case_id"], event_type="PACKAGE_WRITTEN",
                 actor_type=ActorType.HUMAN, actor_id=authorised_by.user_id, actor_role=authorised_by.role.value,
                 payload={"package_version": pkg["package_version"], "package_sha256": art["data_sha256"],
                          "sink": "StubResponseSink", "sink_receipt": receipt,
                          "content_sha256": sha256_hex(canonical(pkg)), "outcome": w["outcome"],
                          "change_reason": change_reason})
    _bump(conn, case, final_outcome=w["outcome"])
    return _move(conn, repo.get_case(conn, tenant_id=case["tenant_id"], case_id=case["case_id"]),
                 S.SUBMITTED_STUB, authorised_by, reason=f"package v{pkg['package_version']} written to stub sink")
