"""Read model over `cases` + `case_artifacts` used by actions, views and export. OWNER: web agent.

Artifact JSON shapes are `domain.to_jsonable` of the domain dataclasses (ADR-011). This module
never writes. The reviewer's "working decision" is the proposal (decision artifact) overlaid by
the latest review record that carries a `working` block (EDIT / APPROVE records).
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from disputes.db import repo
from disputes.domain import ArtifactKind, ClaimFinding, EscalationReason, Outcome

APPROVABLE_OUTCOMES = (Outcome.VERIFIED_AS_REPORTED.value, Outcome.MODIFY.value, Outcome.DELETE.value)
NARRATIVE_FAIL_REASONS = (EscalationReason.DRAFT_INVALID.value, EscalationReason.LLM_UNAVAILABLE.value)
MIN_REASON_CHARS = 10


@dataclass
class CaseBundle:
    case: dict
    artifacts: dict = field(default_factory=dict)       # kind -> latest data (or None)
    artifact_meta: dict = field(default_factory=dict)   # kind -> {version, sha256, created_by, created_at}
    reviews: list = field(default_factory=list)         # review artifact rows (oldest first)
    packages: list = field(default_factory=list)        # package artifact rows (oldest first)
    drafts: list = field(default_factory=list)          # all draft versions (oldest first)
    attachments: list = field(default_factory=list)

    def get(self, kind) -> object:
        return self.artifacts.get(str(kind))

    @property
    def claims(self) -> list[dict]:
        return list(self.get(ArtifactKind.CLAIMS) or [])

    @property
    def evidence(self) -> list[dict]:
        return list(self.get(ArtifactKind.EVIDENCE) or [])

    @property
    def evidence_ids(self) -> set[str]:
        return {e["evidence_id"] for e in self.evidence}


def load_bundle(conn, *, tenant_id: str, case_id: str, case: dict | None = None) -> CaseBundle:
    """Raises repo.NotFound for a case outside `tenant_id`."""
    case = case or repo.get_case(conn, tenant_id=tenant_id, case_id=case_id)
    b = CaseBundle(case=case)
    for row in repo.artifact_history(conn, tenant_id=tenant_id, case_id=case_id):
        k = row["kind"]
        b.artifacts[k] = row["data"]          # history is ordered by id, so the last wins
        b.artifact_meta[k] = {"version": row["version"], "sha256": row["data_sha256"],
                              "created_by": row["created_by"], "created_at": row["created_at"]}
        if k == ArtifactKind.REVIEW.value:
            b.reviews.append(row)
        elif k == ArtifactKind.PACKAGE.value:
            b.packages.append(row)
        elif k == ArtifactKind.DRAFT.value:
            b.drafts.append(row)
    b.attachments = repo.list_attachments(conn, tenant_id=tenant_id, case_id=case_id)
    return b


# ---------------------------------------------------------------- proposal and working state
def proposal(b: CaseBundle) -> dict:
    """What the system proposed: an approvable outcome or None (escalated / out of scope / no decision)."""
    d = b.get(ArtifactKind.DECISION)
    outcome = (d or {}).get("outcome") or b.case.get("proposed_outcome")
    if outcome not in APPROVABLE_OUTCOMES:
        outcome = None
    corrections = list((d or {}).get("corrections") or []) if outcome == Outcome.MODIFY.value else []
    return {"outcome": outcome, "corrections": corrections}


def base_working(b: CaseBundle) -> dict:
    p = proposal(b)
    return {"outcome": p["outcome"], "corrections": p["corrections"], "claim_findings": {}, "narrative": None}


def working_state(b: CaseBundle) -> dict:
    for row in reversed(b.reviews):
        w = row["data"].get("working")
        if w is not None:
            return w
    return base_working(b)


def departs_from_proposal(b: CaseBundle, w: dict) -> bool:
    p = proposal(b)
    return (w["outcome"] != p["outcome"] or _norm_corr(w["corrections"]) != _norm_corr(p["corrections"])
            or bool(w.get("claim_findings")) or w.get("narrative") is not None)


def _norm_corr(cs) -> list:
    return sorted((c.get("month"), c.get("field"), c.get("corrected")) for c in cs or [])


# ---------------------------------------------------------------- claim findings
def valid_system_finding(c: dict, evidence_ids: set[str]) -> bool:
    f = c.get("finding")
    if f in (ClaimFinding.SUPPORTED.value, ClaimFinding.CONTRADICTED.value):
        ids = c.get("evidence_ids") or []
        return bool(ids) and all(i in evidence_ids for i in ids)
    if f == ClaimFinding.NOT_ADDRESSABLE.value:
        return bool((c.get("reason") or "").strip())
    return False


def human_finding_error(f: dict, evidence_ids: set[str]) -> str | None:
    """None if a human finding is valid, else the reason it is not (R-17)."""
    kind = f.get("finding")
    if kind not in {x.value for x in ClaimFinding}:
        return "finding must be SUPPORTED, CONTRADICTED or NOT_ADDRESSABLE"
    if kind == ClaimFinding.NOT_ADDRESSABLE.value:
        if len((f.get("reason") or "").strip()) < MIN_REASON_CHARS:
            return f"NOT_ADDRESSABLE needs a reason of at least {MIN_REASON_CHARS} characters"
        return None
    ids = f.get("evidence_ids") or []
    if not ids:
        return f"{kind} needs at least one evidence ID"
    unknown = [i for i in ids if i not in evidence_ids]
    if unknown:
        return f"unknown evidence ID(s): {', '.join(unknown)}"
    return None


def effective_claims(b: CaseBundle, w: dict | None = None) -> list[dict]:
    """Claims with the human finding (if any) overlaid; `finding_source` = SYSTEM | HUMAN | None."""
    w = w or working_state(b)
    ev = b.evidence_ids
    out = []
    for c in b.claims:
        h = (w.get("claim_findings") or {}).get(c["claim_id"])
        if h:
            out.append({**c, "finding": h["finding"], "evidence_ids": h.get("evidence_ids") or [],
                        "reason": h.get("reason") or "", "finding_source": "HUMAN", "system_finding": c.get("finding")})
        else:
            out.append({**c, "finding_source": "SYSTEM" if valid_system_finding(c, ev) else None,
                        "system_finding": c.get("finding")})
    return out


def claims_needing_finding(b: CaseBundle, w: dict | None = None) -> list[str]:
    w = w or working_state(b)
    human = w.get("claim_findings") or {}
    ev = b.evidence_ids
    return [c["claim_id"] for c in b.claims
            if not valid_system_finding(c, ev) and not (c["claim_id"] in human
                                                        and human_finding_error(human[c["claim_id"]], ev) is None)]


# ---------------------------------------------------------------- narrative
def draft_failed(b: CaseBundle) -> bool:
    d = b.get(ArtifactKind.DRAFT)
    if any(r in NARRATIVE_FAIL_REASONS for r in (b.case.get("escalation_reasons") or [])):
        return True
    return d is None or not d.get("valid", False) or not d.get("sentences")


def system_draft(b: CaseBundle) -> dict | None:
    """The newest draft written by the system/model (human narrative versions are separate)."""
    for row in reversed(b.drafts):
        if not row["data"].get("human_authored"):
            return row["data"]
    return None


def needs_human_narrative(b: CaseBundle, w: dict | None = None) -> str | None:
    """Why the reviewer must write the narrative, or None."""
    w = w or working_state(b)
    sd = system_draft(b)
    if any(r in NARRATIVE_FAIL_REASONS for r in (b.case.get("escalation_reasons") or [])) or \
            sd is None or not sd.get("valid", False) or not sd.get("sentences"):
        return "the drafted narrative failed validation or is missing"
    if w["outcome"] != proposal(b)["outcome"]:
        return "the outcome differs from the proposal, so the drafted narrative no longer matches it"
    if _norm_corr(w["corrections"]) != _norm_corr(proposal(b)["corrections"]):
        return "the corrected fields differ from the proposal, so the drafted narrative no longer matches them"
    return None


def narrative_sentences(b: CaseBundle, w: dict | None = None) -> list[dict]:
    w = w or working_state(b)
    if w.get("narrative") is not None:
        return list(w["narrative"])
    sd = system_draft(b)
    return list((sd or {}).get("sentences") or [])


_SENT_SPLIT = re.compile(r"(?<=[.!?])\s+")


def human_sentences(text: str) -> list[dict]:
    parts = [s.strip() for s in _SENT_SPLIT.split((text or "").strip()) if s.strip()]
    return [{"text": s, "source": "HUMAN", "template_id": None, "evidence_ids": [], "quote_spans": []}
            for s in parts]


def word_count(sentences: list[dict]) -> int:
    return sum(len(s["text"].split()) for s in sentences)


# ---------------------------------------------------------------- approval blockers
def approval_blockers(b: CaseBundle, *, narrative_max_words: int, w: dict | None = None) -> list[str]:
    w = w or working_state(b)
    out = []
    if w["outcome"] not in APPROVABLE_OUTCOMES:
        out.append("Choose an outcome (Verify, Modify or Delete) with Edit before approving.")
    if w["outcome"] == Outcome.MODIFY.value and not w["corrections"]:
        out.append("A Modify outcome needs at least one corrected field.")
    missing = claims_needing_finding(b, w)
    if missing:
        out.append("Enter a finding for each claim without a valid one: " + ", ".join(missing) + ".")
    why = needs_human_narrative(b, w)
    if why and w.get("narrative") is None:
        out.append(f"Write the narrative yourself: {why}.")
    sents = narrative_sentences(b, w)
    if not sents:
        out.append("The response has no narrative.")
    elif word_count(sents) > narrative_max_words:
        out.append(f"The narrative is {word_count(sents)} words; the limit is {narrative_max_words}.")
    return out


# ---------------------------------------------------------------- versions (R-20, R-22)
def versions_for_case(conn, b: CaseBundle) -> dict:
    d = b.get(ArtifactKind.DECISION) or {}
    sd = system_draft(b) or {}
    s = b.get(ArtifactKind.SUSPICION) or {}
    models, prompts = set(), set()
    for e in repo.audit_events_for_case(conn, tenant_id=b.case["tenant_id"], case_id=b.case["case_id"]):
        p = e["payload"] or {}
        for src in (p, p.get("llm_call") or {}):
            if isinstance(src, dict):
                if src.get("model_id"):
                    models.add(src["model_id"])
                if src.get("prompt_template_id") or src.get("prompt_sha256"):
                    prompts.add(f"{src.get('prompt_template_id') or '?'}@{(src.get('prompt_sha256') or '')[:12]}")
    return {
        "rules_version": d.get("rules_version"),
        "decision_table_versions": d.get("table_versions") or {},
        "template_library_version": sd.get("template_library_version"),
        "suspicion_patterns_version": s.get("patterns_version"),
        "model_ids": sorted(models),
        "prompt_templates": sorted(prompts),
        "artifact_versions": {k: v["version"] for k, v in sorted(b.artifact_meta.items())},
    }
