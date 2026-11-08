"""Presentation models for the templates. OWNER: web agent. No writes here.

All untrusted text (letters, free text, notes) is passed to Jinja2 as plain strings and rendered
with autoescape on; quote highlights are built as segment lists, never as HTML strings (ADR-007).
"""
from __future__ import annotations

import json
from datetime import date, datetime, timezone

from disputes.db import repo
from disputes.domain import ArtifactKind, CaseState as S, Role
from disputes.web import casedata as cd
from disputes.web.pii import mask_account

OPEN_STATES = [s.value for s in (S.RECEIVED, S.CLASSIFIED, S.INVESTIGATING, S.DRAFT_READY, S.ESCALATED,
                                 S.IN_REVIEW, S.AWAITING_SECOND_APPROVAL, S.APPROVED)]
COMPLETED_STATES = [S.SUBMITTED_STUB.value, S.OUT_OF_SCOPE.value]

STATE_LABELS = {
    "RECEIVED": "Received", "CLASSIFIED": "Classified", "OUT_OF_SCOPE": "Out of scope",
    "INVESTIGATING": "Investigating", "DRAFT_READY": "Draft ready", "ESCALATED": "Escalated",
    "IN_REVIEW": "In review", "AWAITING_SECOND_APPROVAL": "Awaiting 2nd approval", "APPROVED": "Approved",
    "SUBMITTED_STUB": "Submitted (stub)",
}
OUTCOME_LABELS = {"VERIFIED_AS_REPORTED": "Verified as reported", "MODIFY": "Modify", "DELETE": "Delete",
                  "ESCALATED": "Escalated", "OUT_OF_SCOPE": "Out of scope"}
CLOCK_LABELS = {"ON_TRACK": "On track", "AT_RISK": "At risk", "BREACHED": "Breached"}


def label(kind: str, v) -> str:
    table = {"state": STATE_LABELS, "outcome": OUTCOME_LABELS, "clock": CLOCK_LABELS}[kind]
    return table.get(v, v or "—")


# ---------------------------------------------------------------- highlights
def highlight_segments(text: str, spans: list[tuple[int, int, str]]) -> list[dict]:
    """Split `text` into [{text, claim_id|None}] with each (start, end, claim_id) span marked.
    Overlapping or out-of-range spans are clipped; text is never interpreted as markup."""
    text = text or ""
    out, pos = [], 0
    for start, end, cid in sorted((s for s in spans if s[0] is not None), key=lambda s: (s[0], s[1])):
        start, end = max(start, pos), min(end, len(text))
        if start >= end:
            continue
        if start > pos:
            out.append({"text": text[pos:start], "claim_id": None})
        out.append({"text": text[start:end], "claim_id": cid})
        pos = end
    if pos < len(text):
        out.append({"text": text[pos:], "claim_id": None})
    return out


def sources_with_highlights(b: cd.CaseBundle) -> list[dict]:
    dispute = b.get(ArtifactKind.DISPUTE) or {}
    texts = []
    if dispute.get("free_text"):
        texts.append({"source_id": "FREE_TEXT", "title": "ACDV free text", "text": dispute["free_text"],
                      "sha256": None})
    for a in b.attachments:
        texts.append({"source_id": a["attachment_id"], "title": a["file_name"], "text": a["extracted_text"],
                      "sha256": a["sha256"]})
    by_src: dict[str, list] = {}
    for c in b.claims:
        if c.get("span"):
            by_src.setdefault(c["source_id"], []).append((c["span"][0], c["span"][1], c["claim_id"]))
    for t in texts:
        t["segments"] = highlight_segments(t["text"], by_src.get(t["source_id"], []))
    return texts


# ---------------------------------------------------------------- deadline ruler
def deadline_ruler(case: dict, today: date | None = None) -> dict | None:
    rec, due, tgt = case.get("date_received"), case.get("response_due_date"), case.get("internal_target_date")
    if not (rec and due) or due <= rec:
        return None
    today = today or datetime.now(timezone.utc).date()
    span = (due - rec).days

    def pct(d):
        return None if d is None else max(0.0, min(100.0, (d - rec).days * 100.0 / span))
    return {"received": rec, "due": due, "target": tgt, "today": today, "target_pct": pct(tgt),
            "today_pct": pct(today), "days_to_due": (due - today).days,
            "days_to_target": (tgt - today).days if tgt else None, "past_due": today > due}


# ---------------------------------------------------------------- escalations with R-29 rule IDs
def escalation_rows(b: cd.CaseBundle) -> list[dict]:
    decision = b.get(ArtifactKind.DECISION) or {}
    firings = decision.get("firings") or []
    intake = b.get(ArtifactKind.INTAKE) or {}
    cls = b.get(ArtifactKind.CLASSIFICATION) or {}
    reasons = list(dict.fromkeys(list(b.case.get("escalation_reasons") or []) + list(decision.get(
        "escalation_reasons") or []) + list(intake.get("escalations") or []) + list(cls.get("escalations") or [])))
    rows = []
    for r in reasons:
        fs = [f for f in firings if f.get("result") == r]
        origin = ("decision" if fs else "intake" if r in (intake.get("escalations") or [])
                  else "classification" if r in (cls.get("escalations") or []) else "pipeline")
        rows.append({"reason": r, "origin": origin,
                     "firings": [{"rule_id": f["rule_id"], "rule_version": f.get("rule_version"),
                                  "evidence_ids": f.get("evidence_ids") or [], "detail": f.get("detail")}
                                 for f in fs]})
    return rows


def outcome_firings(b: cd.CaseBundle) -> list[dict]:
    d = b.get(ArtifactKind.DECISION) or {}
    return [f for f in (d.get("firings") or []) if f.get("result") == d.get("outcome")]


# ---------------------------------------------------------------- evidence rendering
def evidence_rows(b: cd.CaseBundle) -> list[dict]:
    out = []
    for e in b.evidence:
        content = e.get("content") or {}
        fields = []
        for k, v in content.items() if isinstance(content, dict) else []:
            fields.append((k, v if isinstance(v, (str, int, float, bool)) or v is None
                           else json.dumps(v, sort_keys=True, ensure_ascii=False)))
        out.append({**e, "fields": fields})
    return out


def timeline(conn, case: dict, *, client_view: bool = False) -> list[dict]:
    evs = repo.audit_events_for_case(conn, tenant_id=case["tenant_id"], case_id=case["case_id"])
    out = []
    for e in evs:
        p = e["payload"] or {}
        if client_view and e["event_type"] != "STATE_CHANGED":
            continue
        out.append({"event_id": e["event_id"], "at": e["occurred_at"], "type": e["event_type"],
                    "actor": None if client_view else e["actor_id"],
                    "actor_role": e["actor_role"] if not client_view else (
                        "Our analyst team" if e["actor_type"] == "HUMAN" else "Platform"),
                    "from": p.get("from"), "to": p.get("to"),
                    "action": p.get("action"), "reason": None if client_view else (p.get("reason_text") or p.get("reason"))})
    return out


def available_actions(case: dict, role: Role) -> list[str]:
    st = case["state"]
    acting = role in (Role.SPECIALIST, Role.SUPERVISOR, Role.ADMIN)
    sup = role in (Role.SUPERVISOR, Role.ADMIN)
    acts = []
    if not acting:
        return acts
    if st == S.IN_REVIEW.value:
        acts += ["edit", "approve", "escalate", "out_of_scope"]
    if st == S.DRAFT_READY.value:
        acts += ["escalate"]
    if st == S.ESCALATED.value and sup:
        acts += ["take", "out_of_scope"]
    if st == S.AWAITING_SECOND_APPROVAL.value:
        if role == Role.SUPERVISOR:
            acts += ["second_approve", "reject_second"]
        acts += ["escalate"]
    if st == S.SUBMITTED_STUB.value and sup:
        acts += ["reopen"]
    return acts


def case_view(conn, b: cd.CaseBundle, *, role: Role, cfg) -> dict:
    w = cd.working_state(b)
    prior = None
    if b.case.get("repeat_of_case_id"):
        try:
            prior = repo.get_case(conn, tenant_id=b.case["tenant_id"], case_id=b.case["repeat_of_case_id"])
        except repo.NotFound:
            prior = None
    sd = cd.system_draft(b)
    return {
        "case": b.case, "dispute": b.get(ArtifactKind.DISPUTE) or {},
        "intake": b.get(ArtifactKind.INTAKE) or {}, "suspicion": b.get(ArtifactKind.SUSPICION) or {},
        "classification": b.get(ArtifactKind.CLASSIFICATION) or {}, "decision": b.get(ArtifactKind.DECISION) or {},
        "evidence": evidence_rows(b), "comparison": b.get(ArtifactKind.COMPARISON) or [],
        "claims": cd.effective_claims(b, w), "sources": sources_with_highlights(b),
        "narrative": cd.narrative_sentences(b, w), "narrative_is_human": w.get("narrative") is not None,
        "system_draft": sd, "draft_failed": cd.draft_failed(b),
        "needs_human_narrative": cd.needs_human_narrative(b, w),
        "escalations": escalation_rows(b), "outcome_firings": outcome_firings(b),
        "ruler": deadline_ruler(b.case), "prior": prior,
        "proposal": cd.proposal(b), "working": w, "departs": cd.departs_from_proposal(b, w),
        "blockers": cd.approval_blockers(b, narrative_max_words=cfg.narrative_max_words, w=w)
        if b.case["state"] == S.IN_REVIEW.value else [],
        "missing_findings": cd.claims_needing_finding(b, w),
        "reviews": [r["data"] | {"at": r["created_at"], "version": r["version"]} for r in b.reviews],
        "packages": [{**r["data"], "at": r["created_at"], "sha256": r["data_sha256"]} for r in b.packages],
        "attachments": b.attachments, "actions": available_actions(b.case, role),
        "account_masked": mask_account(b.case.get("account_number")),
        "timeline": timeline(conn, b.case),
    }
