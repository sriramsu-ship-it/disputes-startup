"""R-17 / R-18 / R-19 / R-20 / R-21 / R-24 service-layer rules (disputes.web.actions)."""
from __future__ import annotations

import pytest

from disputes.db import repo
from disputes.domain import ArtifactKind
from disputes.web import actions as act
from disputes.web import casedata as cd
from test_web_support import A, B, actor, case, seeded, sink  # noqa: F401

R = dict(reason_code="EVIDENCE_MISREAD", reason_text="Ledger shows the payment posted on time.")


def state(conn, cid, tenant=A):
    return repo.get_case(conn, tenant_id=tenant, case_id=cid)["state"]


def events(conn, cid, tenant=A):
    return repo.audit_events_for_case(conn, tenant_id=tenant, case_id=cid)


def reviewed(conn, cid, uid="u-spec", tenant=A):
    act.open_case(conn, tenant_id=tenant, case_id=cid, actor=actor(uid))
    return repo.get_case(conn, tenant_id=tenant, case_id=cid)


# ------------------------------------------------------------------ open
def test_open_draft_ready_moves_to_in_review_and_records_metrics(conn, seeded):
    case(conn, "C1", "verify")
    act.open_case(conn, tenant_id=A, case_id="C1", actor=actor("u-spec"))
    row = repo.get_case(conn, tenant_id=A, case_id="C1")
    assert row["state"] == "IN_REVIEW" and row["assigned_to"] == "u-spec"
    ev = events(conn, "C1")
    assert ev[-1]["event_type"] == "STATE_CHANGED" and ev[-1]["payload"]["to"] == "IN_REVIEW"
    assert ev[-1]["actor_id"] == "u-spec" and ev[-1]["actor_role"] == "SPECIALIST"
    act.open_case(conn, tenant_id=A, case_id="C1", actor=actor("u-sup1"))
    m = [r["metric"] for r in conn.execute("SELECT metric FROM case_metrics WHERE case_id='C1' ORDER BY id")]
    assert m == ["opened", "first_viewed", "opened"]


def test_auditor_open_is_read_only_and_audited(conn, seeded):
    case(conn, "C1", "verify")
    act.open_case(conn, tenant_id=A, case_id="C1", actor=actor("u-aud"))
    assert state(conn, "C1") == "DRAFT_READY"
    ev = events(conn, "C1")
    assert [e["event_type"] for e in ev] == ["CASE_READ"] and ev[0]["actor_role"] == "AUDITOR"
    with pytest.raises(act.ActionForbidden):
        act.escalate(conn, tenant_id=A, case_id="C1", actor=actor("u-aud"), reason_text="auditors cannot act")


# ------------------------------------------------------------------ approve (happy path, R-20)
def test_approve_without_changes_writes_package_and_submits(conn, seeded, sink):
    case(conn, "C1", "verify")
    reviewed(conn, "C1")
    row = act.approve(conn, tenant_id=A, case_id="C1", actor=actor("u-spec"), sink=sink)
    assert row["state"] == "SUBMITTED_STUB"
    assert repo.get_case(conn, tenant_id=A, case_id="C1")["final_outcome"] == "VERIFIED_AS_REPORTED"
    assert len(sink.packages) == 1
    pkg = repo.latest_artifact(conn, tenant_id=A, case_id="C1", kind=ArtifactKind.PACKAGE)["data"]
    assert pkg["package_version"] == 1 and pkg["dfAuthorizedName"] == "Sam Okafor (SYNTHETIC)"
    assert pkg["outcome"] == "VERIFIED_AS_REPORTED" and pkg["narrative"].startswith("Our records show")
    assert pkg["versions"]["rules_version"] == "1.0.0" and pkg["synthetic"] is True
    assert pkg["sink_receipt"] and pkg["supersedes_package_sha256"] is None
    types = [e["event_type"] for e in events(conn, "C1")]
    assert types.count("REVIEW_ACTION") == 1 and "PACKAGE_WRITTEN" in types
    to = [e["payload"]["to"] for e in events(conn, "C1") if e["event_type"] == "STATE_CHANGED"]
    assert to == ["IN_REVIEW", "APPROVED", "SUBMITTED_STUB"]
    rev = repo.latest_artifact(conn, tenant_id=A, case_id="C1", kind=ArtifactKind.REVIEW)["data"]
    assert rev["action"] == "APPROVE" and rev["actor_id"] == "u-spec" and rev["departs_from_proposal"] is False
    d = conn.execute("SELECT detail FROM case_metrics WHERE case_id='C1' AND metric='decided'").fetchone()
    assert d["detail"]["override"] is False


def test_approval_rolls_back_if_the_package_cannot_be_written(conn, seeded):
    case(conn, "C1", "verify")
    reviewed(conn, "C1")

    class Broken:
        def write_package(self, pkg):
            raise RuntimeError("sink down")
    with pytest.raises(RuntimeError):
        act.approve(conn, tenant_id=A, case_id="C1", actor=actor("u-spec"), sink=Broken())
    assert state(conn, "C1") == "IN_REVIEW"
    assert repo.latest_artifact(conn, tenant_id=A, case_id="C1", kind=ArtifactKind.REVIEW) is None
    assert "REVIEW_ACTION" not in [e["event_type"] for e in events(conn, "C1")]


def test_approve_needs_in_review_and_acting_role(conn, seeded, sink):
    case(conn, "C1", "verify")
    with pytest.raises(act.ActionError):
        act.approve(conn, tenant_id=A, case_id="C1", actor=actor("u-spec"), sink=sink)   # still DRAFT_READY
    reviewed(conn, "C1")
    with pytest.raises(act.ActionForbidden):
        act.approve(conn, tenant_id=A, case_id="C1", actor=actor("u-aud"), sink=sink)
    with pytest.raises(act.ActionForbidden):
        act.approve(conn, tenant_id=A, case_id="C1", actor=actor("u-client-a"), sink=sink)


# ------------------------------------------------------------------ reason codes (R-17)
@pytest.mark.parametrize("kw,field", [
    (dict(reason_code=None, reason_text="a long enough reason"), "reason_code"),
    (dict(reason_code="NOT_A_CODE", reason_text="a long enough reason"), "reason_code"),
    (dict(reason_code="OTHER", reason_text="too short"), "reason_text"),
    (dict(reason_code="OTHER", reason_text="          x"), "reason_text"),
])
def test_edit_requires_reason_code_and_ten_chars(conn, seeded, kw, field):
    case(conn, "C1", "verify")
    reviewed(conn, "C1")
    with pytest.raises(act.ActionError) as e:
        act.edit(conn, tenant_id=A, case_id="C1", actor=actor("u-spec"), outcome="MODIFY",
                 corrections=[{"month": "2026-02", "reported": "1", "corrected": "0"}], **kw)
    assert e.value.field == field


def test_delete_requires_reason(conn, seeded):
    case(conn, "C1", "verify")
    reviewed(conn, "C1")
    with pytest.raises(act.ActionError) as e:
        act.edit(conn, tenant_id=A, case_id="C1", actor=actor("u-spec"), outcome="DELETE", reason_code=None,
                 reason_text=None)
    assert e.value.field == "reason_code"


def test_modify_needs_corrections_and_a_human_narrative(conn, seeded, sink):
    case(conn, "C1", "verify")
    reviewed(conn, "C1")
    with pytest.raises(act.ActionError) as e:
        act.edit(conn, tenant_id=A, case_id="C1", actor=actor("u-spec"), outcome="MODIFY", **R)
    assert e.value.field == "corrections"
    act.edit(conn, tenant_id=A, case_id="C1", actor=actor("u-spec"), outcome="MODIFY",
             corrections=[{"month": "2026-02", "reported": "1", "corrected": "0"}], **R)
    with pytest.raises(act.ActionError) as e:
        act.approve(conn, tenant_id=A, case_id="C1", actor=actor("u-spec"), sink=sink)
    assert "narrative" in str(e.value)
    act.edit(conn, tenant_id=A, case_id="C1", actor=actor("u-spec"), reason_code="NARRATIVE_EDIT_ONLY",
             reason_text="Narrative rewritten to match the change.",
             narrative="We corrected the February 2026 rating. The payment posted on time.")
    row = act.approve(conn, tenant_id=A, case_id="C1", actor=actor("u-spec"), sink=sink)
    assert row["state"] == "SUBMITTED_STUB"
    pkg = sink.packages[-1]
    assert pkg["outcome"] == "MODIFY" and pkg["corrections"][0]["corrected"] == "0"
    assert {s["source"] for s in pkg["narrative_sentences"]} == {"HUMAN"} and len(pkg["narrative_sentences"]) == 2
    drafts = repo.artifact_history(conn, tenant_id=A, case_id="C1", kind=ArtifactKind.DRAFT)
    assert len(drafts) == 2 and drafts[-1]["data"]["human_authored"] and drafts[-1]["created_by"] == "u-spec"
    d = conn.execute("SELECT detail FROM case_metrics WHERE case_id='C1' AND metric='decided'").fetchone()
    assert d["detail"]["override"] is True and d["detail"]["reason_code"] == "NARRATIVE_EDIT_ONLY"


def test_edit_rejects_no_change_and_bad_inputs(conn, seeded):
    case(conn, "C1", "verify")
    reviewed(conn, "C1")
    with pytest.raises(act.ActionError, match="nothing changed"):
        act.edit(conn, tenant_id=A, case_id="C1", actor=actor("u-spec"), outcome="VERIFIED_AS_REPORTED", **R)
    with pytest.raises(act.ActionError) as e:
        act.edit(conn, tenant_id=A, case_id="C1", actor=actor("u-spec"), outcome="ESCALATED", **R)
    assert e.value.field == "outcome"
    with pytest.raises(act.ActionError) as e:
        act.edit(conn, tenant_id=A, case_id="C1", actor=actor("u-spec"), outcome="MODIFY",
                 corrections=[{"month": "Feb 2026", "corrected": "0"}], **R)
    assert e.value.field == "corrections"
    with pytest.raises(act.ActionError) as e:
        act.edit(conn, tenant_id=A, case_id="C1", actor=actor("u-spec"), narrative=" ".join(["word"] * 151), **R)
    assert e.value.field == "narrative"


# ------------------------------------------------------------------ unresolved claims block approval (R-17)
def test_unaddressed_claim_blocks_approval_until_human_finding(conn, seeded, sink):
    case(conn, "C1", "unaddressed")
    with pytest.raises(PermissionError):           # ESCALATED -> IN_REVIEW is supervisor-only
        act.take_for_review(conn, tenant_id=A, case_id="C1", actor=actor("u-spec"))
    act.take_for_review(conn, tenant_id=A, case_id="C1", actor=actor("u-sup1"))
    b = cd.load_bundle(conn, tenant_id=A, case_id="C1")
    assert cd.claims_needing_finding(b) == ["C2"]
    blockers = cd.approval_blockers(b, narrative_max_words=150)
    assert any("C2" in x for x in blockers) and any("outcome" in x for x in blockers)

    sup = actor("u-sup1")
    for bad in ({"finding": "CONTRADICTED", "evidence_ids": ["EV-NOPE"]},
                {"finding": "CONTRADICTED", "evidence_ids": []},
                {"finding": "NOT_ADDRESSABLE", "reason": "short"},
                {"finding": "MAYBE"}):
        with pytest.raises(act.ActionError) as e:
            act.edit(conn, tenant_id=A, case_id="C1", actor=sup, claim_findings={"C2": bad}, **R)
        assert e.value.field == "claim_findings"
    with pytest.raises(act.ActionError):
        act.edit(conn, tenant_id=A, case_id="C1", actor=sup, claim_findings={"C9": {"finding": "SUPPORTED"}}, **R)

    act.edit(conn, tenant_id=A, case_id="C1", actor=sup, outcome="VERIFIED_AS_REPORTED", **R)
    with pytest.raises(act.ActionError, match="C2"):
        act.approve(conn, tenant_id=A, case_id="C1", actor=sup, sink=sink)
    act.edit(conn, tenant_id=A, case_id="C1", actor=sup, reason_code="CLAIM_FINDING_ENTERED",
             reason_text="Cycle record contradicts the claim.",
             claim_findings={"C2": {"finding": "CONTRADICTED", "evidence_ids": ["EV-CYCLE-2026-02"]}})
    with pytest.raises(act.ActionError, match="narrative"):   # no proposal + no draft -> reviewer writes it
        act.approve(conn, tenant_id=A, case_id="C1", actor=sup, sink=sink)
    act.edit(conn, tenant_id=A, case_id="C1", actor=sup, narrative="The February 2026 payment was 41 days late.", **R)
    assert cd.claims_needing_finding(cd.load_bundle(conn, tenant_id=A, case_id="C1")) == []
    assert act.approve(conn, tenant_id=A, case_id="C1", actor=sup, sink=sink)["state"] == "SUBMITTED_STUB"


def test_validator_failure_means_reviewer_writes_narrative(conn, seeded, sink):
    case(conn, "C1", "draft_invalid")
    act.take_for_review(conn, tenant_id=A, case_id="C1", actor=actor("u-sup1"))
    b = cd.load_bundle(conn, tenant_id=A, case_id="C1")
    assert cd.proposal(b)["outcome"] == "VERIFIED_AS_REPORTED"    # deterministic proposal still shown (F3)
    with pytest.raises(act.ActionError, match="narrative"):
        act.approve(conn, tenant_id=A, case_id="C1", actor=actor("u-sup1"), sink=sink)
    act.edit(conn, tenant_id=A, case_id="C1", actor=actor("u-sup1"), reason_code="NARRATIVE_EDIT_ONLY",
             reason_text="Validator failed twice; narrative written by hand.",
             narrative="Our records show the February 2026 payment was 41 days late.")
    act.approve(conn, tenant_id=A, case_id="C1", actor=actor("u-sup1"), sink=sink)
    assert sink.packages[-1]["narrative_sentences"][0]["source"] == "HUMAN"
    assert sink.packages[-1]["outcome"] == "VERIFIED_AS_REPORTED"


# ------------------------------------------------------------------ second approval + separation of duties
def test_delete_needs_second_approval_by_a_different_supervisor(conn, seeded, sink):
    case(conn, "C1", "verify")
    reviewed(conn, "C1", "u-sup1")
    sup1, sup2 = actor("u-sup1"), actor("u-sup2")
    act.edit(conn, tenant_id=A, case_id="C1", actor=sup1, outcome="DELETE", reason_code="DATA_UNVERIFIABLE",
             reason_text="Cannot verify the account history.", narrative="We deleted the account from reporting.")
    row = act.approve(conn, tenant_id=A, case_id="C1", actor=sup1, sink=sink)
    assert row["state"] == "AWAITING_SECOND_APPROVAL" and sink.packages == []
    assert repo.latest_artifact(conn, tenant_id=A, case_id="C1", kind=ArtifactKind.PACKAGE) is None
    with pytest.raises(act.ActionForbidden, match="separation of duties"):
        act.second_approve(conn, tenant_id=A, case_id="C1", actor=sup1, sink=sink)
    with pytest.raises(act.ActionForbidden):
        act.second_approve(conn, tenant_id=A, case_id="C1", actor=actor("u-spec"), sink=sink)
    with pytest.raises(act.ActionForbidden):
        act.second_approve(conn, tenant_id=A, case_id="C1", actor=actor("u-admin"), sink=sink)
    row = act.second_approve(conn, tenant_id=A, case_id="C1", actor=sup2, sink=sink)
    assert row["state"] == "SUBMITTED_STUB"
    pkg = sink.packages[-1]
    assert pkg["outcome"] == "DELETE" and pkg["dfAuthorizedName"] == "Rene Castillo (SYNTHETIC)"
    assert [a["user_id"] for a in pkg["approvals"]] == ["u-sup1", "u-sup2"]


def test_supervisor_who_edited_cannot_second_approve(conn, seeded, sink):
    case(conn, "C1", "verify")
    reviewed(conn, "C1", "u-spec")
    act.edit(conn, tenant_id=A, case_id="C1", actor=actor("u-sup1"), reason_code="NARRATIVE_EDIT_ONLY",
             reason_text="Tightened the wording of the narrative.",
             narrative="Our records show the February 2026 payment was 41 days late.")
    act.edit(conn, tenant_id=A, case_id="C1", actor=actor("u-spec"), outcome="DELETE", **R)
    act.approve(conn, tenant_id=A, case_id="C1", actor=actor("u-spec"), sink=sink)
    with pytest.raises(act.ActionForbidden):
        act.second_approve(conn, tenant_id=A, case_id="C1", actor=actor("u-sup1"), sink=sink)
    assert act.second_approve(conn, tenant_id=A, case_id="C1", actor=actor("u-sup2"), sink=sink)["state"] == \
        "SUBMITTED_STUB"


def test_high_suspicion_needs_second_approval(conn, seeded, sink):
    case(conn, "C1", "high")
    reviewed(conn, "C1", "u-sup1")
    row = act.approve(conn, tenant_id=A, case_id="C1", actor=actor("u-sup1"), sink=sink)
    assert row["state"] == "AWAITING_SECOND_APPROVAL" and not sink.packages
    rev = repo.latest_artifact(conn, tenant_id=A, case_id="C1", kind=ArtifactKind.REVIEW)["data"]
    assert rev["second_approval_required"] == "HIGH suspicious-content flag"
    with pytest.raises(act.ActionForbidden):
        act.second_approve(conn, tenant_id=A, case_id="C1", actor=actor("u-sup1"), sink=sink)
    act.second_approve(conn, tenant_id=A, case_id="C1", actor=actor("u-sup2"), sink=sink)
    assert sink.packages[-1]["outcome"] == "VERIFIED_AS_REPORTED"   # the flag never changes the outcome


def test_reject_second_approval_returns_to_review_with_reason(conn, seeded, sink):
    case(conn, "C1", "high")
    reviewed(conn, "C1")
    act.approve(conn, tenant_id=A, case_id="C1", actor=actor("u-spec"), sink=sink)
    with pytest.raises(act.ActionError):
        act.reject_second_approval(conn, tenant_id=A, case_id="C1", actor=actor("u-sup2"), reason_text="no")
    act.reject_second_approval(conn, tenant_id=A, case_id="C1", actor=actor("u-sup2"),
                               reason_text="Injected text needs a closer look first.")
    assert state(conn, "C1") == "IN_REVIEW" and not sink.packages


# ------------------------------------------------------------------ package versioning (R-20)
def test_change_after_submission_creates_new_package_version(conn, seeded, sink):
    case(conn, "C1", "verify")
    reviewed(conn, "C1")
    act.approve(conn, tenant_id=A, case_id="C1", actor=actor("u-spec"), sink=sink)
    v1 = repo.latest_artifact(conn, tenant_id=A, case_id="C1", kind=ArtifactKind.PACKAGE)
    with pytest.raises(act.ActionForbidden):
        act.reopen_submitted(conn, tenant_id=A, case_id="C1", actor=actor("u-spec"), **R)
    with pytest.raises(act.ActionError):
        act.reopen_submitted(conn, tenant_id=A, case_id="C1", actor=actor("u-sup1"), reason_code="OTHER",
                             reason_text="short")
    act.reopen_submitted(conn, tenant_id=A, case_id="C1", actor=actor("u-sup1"),
                         reason_code="ADDITIONAL_EVIDENCE_OUTSIDE_SYSTEM",
                         reason_text="Payment receipt found in the core system.")
    assert state(conn, "C1") == "IN_REVIEW"
    act.edit(conn, tenant_id=A, case_id="C1", actor=actor("u-sup1"), outcome="MODIFY",
             corrections=[{"month": "2026-02", "reported": "1", "corrected": "0"}],
             narrative="We corrected the February 2026 payment rating.", **R)
    act.approve(conn, tenant_id=A, case_id="C1", actor=actor("u-sup1"), sink=sink)
    hist = repo.artifact_history(conn, tenant_id=A, case_id="C1", kind=ArtifactKind.PACKAGE)
    assert [h["version"] for h in hist] == [1, 2]
    assert hist[0]["data"] == v1["data"]                      # v1 untouched (insert-only)
    v2 = hist[1]["data"]
    assert v2["package_version"] == 2 and v2["supersedes_package_sha256"] == v1["data_sha256"]
    assert v2["change_reason"]["reason_code"] == "ADDITIONAL_EVIDENCE_OUTSIDE_SYSTEM"
    assert v2["outcome"] == "MODIFY" and len(sink.packages) == 2


# ------------------------------------------------------------------ escalate / out of scope
def test_escalate_requires_reason_text(conn, seeded):
    case(conn, "C1", "verify")
    reviewed(conn, "C1")
    with pytest.raises(act.ActionError) as e:
        act.escalate(conn, tenant_id=A, case_id="C1", actor=actor("u-spec"), reason_text="hmm")
    assert e.value.field == "reason_text"
    act.escalate(conn, tenant_id=A, case_id="C1", actor=actor("u-spec"),
                 reason_text="Letter mentions a deferral we cannot see.")
    assert state(conn, "C1") == "ESCALATED"
    rev = repo.latest_artifact(conn, tenant_id=A, case_id="C1", kind=ArtifactKind.REVIEW)["data"]
    assert rev["action"] == "ESCALATE" and rev["reason_text"].startswith("Letter")


def test_mark_out_of_scope_rules(conn, seeded):
    case(conn, "C1", "fraud")
    with pytest.raises(act.ActionError) as e:
        act.mark_out_of_scope(conn, tenant_id=A, case_id="C1", actor=actor("u-sup1"), reason_code=None,
                              reason_text="Identity theft handled under 605B.")
    assert e.value.field == "reason_code"
    with pytest.raises(act.ActionForbidden):      # ESCALATED -> OUT_OF_SCOPE needs a supervisor
        act.mark_out_of_scope(conn, tenant_id=A, case_id="C1", actor=actor("u-spec"),
                              reason_code="CLASSIFICATION_WRONG", reason_text="Identity theft handled under 605B.")
    act.mark_out_of_scope(conn, tenant_id=A, case_id="C1", actor=actor("u-sup1"),
                          reason_code="CLASSIFICATION_WRONG", reason_text="Identity theft handled under 605B.")
    row = repo.get_case(conn, tenant_id=A, case_id="C1")
    assert row["state"] == "OUT_OF_SCOPE" and row["final_outcome"] == "OUT_OF_SCOPE"


# ------------------------------------------------------------------ concurrency + tenant isolation
def test_stale_version_is_rejected(conn, seeded, sink):
    case(conn, "C1", "verify")
    row = reviewed(conn, "C1")
    act.edit(conn, tenant_id=A, case_id="C1", actor=actor("u-spec"), narrative="Rewritten narrative here.", **R)
    with pytest.raises(act.StaleCase):
        act.approve(conn, tenant_id=A, case_id="C1", actor=actor("u-spec"), sink=sink,
                    expected_version=row["version"])


def test_actions_are_tenant_scoped(conn, seeded, sink):
    case(conn, "CB", "verify", tenant=B)
    with pytest.raises(repo.NotFound):
        act.open_case(conn, tenant_id=A, case_id="CB", actor=actor("u-spec"))
    with pytest.raises(repo.NotFound):
        act.escalate(conn, tenant_id=A, case_id="CB", actor=actor("u-spec"), reason_text="wrong tenant attempt")
    assert state(conn, "CB", tenant=B) == "DRAFT_READY"


def test_every_review_action_is_in_the_audit_chain(conn, seeded, sink):
    from disputes.audit.chain import GENESIS, event_body, rfc3339, sha256_hex
    case(conn, "C1", "verify")
    reviewed(conn, "C1")
    act.edit(conn, tenant_id=A, case_id="C1", actor=actor("u-spec"), narrative="Rewritten narrative here.", **R)
    act.approve(conn, tenant_id=A, case_id="C1", actor=actor("u-spec"), sink=sink)
    prev = GENESIS
    for e in events(conn, "C1"):
        body = event_body(tenant_id=e["tenant_id"], case_id=e["case_id"], event_type=e["event_type"],
                          actor_type=e["actor_type"], actor_id=e["actor_id"], actor_role=e["actor_role"],
                          occurred_at=rfc3339(e["occurred_at"]), payload_sha256=e["payload_sha256"])
        assert e["case_prev_hash"] == prev and e["case_hash"] == sha256_hex(prev + body)
        prev = e["case_hash"]
    edits = [e for e in events(conn, "C1") if e["event_type"] == "REVIEW_ACTION"]
    assert [e["payload"]["action"] for e in edits] == ["EDIT", "APPROVE"]
    assert edits[0]["payload"]["reason_code"] == "EVIDENCE_MISREAD"
