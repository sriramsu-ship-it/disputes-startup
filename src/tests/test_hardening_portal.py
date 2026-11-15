"""Hardening: client portal fixes (consistent "completed"), R-39 (client reads and downloads audited;
every client state-changing request 403 + audited), R-37 ACCESS_DENIED, client export content,
domain type adoption (ReviewRecord, REOPEN_AFTER_SUBMISSION, Draft.human_authored,
Classification.llm_suspicious). SYNTHETIC data only."""
from __future__ import annotations

import json
from datetime import datetime, timezone

from fastapi.testclient import TestClient

from disputes.agents.llm import OfflineLlmClient
from disputes.config import defaults
from disputes.contracts_bridge import MockSystemOfRecord, acdv_to_dispute
from disputes.domain import ReviewAction, ReviewRecord, Role
from disputes.web import actions as act
from disputes.web import casedata as cd
from disputes.web import portal
from disputes.workflow import pipeline
from test_agents_helpers import FIXTURES
from test_web_support import A, B, actor, app_factory, case, csrf_of, login, seeded, sink  # noqa: F401


def _events(conn, etype, tenant=None):
    q = "SELECT tenant_id, case_id, actor_id, payload FROM audit_events WHERE event_type = %s"
    args = [etype]
    if tenant:
        q += " AND tenant_id = %s"
        args.append(tenant)
    conn.rollback()
    return conn.execute(q + " ORDER BY event_id", args).fetchall()


# ------------------------------------------------------------------ "completed" is consistent
def test_completed_tile_equals_outcome_panel_and_case_list(conn, seeded, app_factory, sink):
    case(conn, "P1", "verify")
    case(conn, "P2", "out_of_scope")       # pipeline-style OUT_OF_SCOPE: no final_outcome
    case(conn, "P3", "submitted")
    case(conn, "P4", "at_risk")
    d = portal.dashboard(conn, tenant_id=A)
    assert d["completed"] == sum(d["by_outcome"].values()) == 2
    assert "OUT_OF_SCOPE" in d["by_outcome"] and "UNKNOWN" not in d["by_outcome"]
    rows = portal.case_list(conn, tenant_id=A)
    assert sum(r["completed"] for r in rows) == d["completed"]
    assert {r["case_id"]: r["outcome"] for r in rows if r["completed"]}["P2"] == "OUT_OF_SCOPE"
    page = login(TestClient(app_factory()), seeded, "u-client-a").get("/client").text
    assert 'data-testid="completed-definition"' in page and "out of scope" in page.lower()
    assert "None completed yet" not in page


# ------------------------------------------------------------------ R-39 reads / downloads audited
def test_client_case_view_and_downloads_are_audited(conn, seeded, app_factory):
    case(conn, "P5", "submitted")
    c = login(TestClient(app_factory()), seeded, "u-client-a")
    assert c.get("/client/cases/P5").status_code == 200
    assert c.get("/client/cases/P5/export.json").status_code == 200
    assert c.get("/client/cases/P5/export.html").status_code == 200
    reads = [r for r in _events(conn, "CASE_READ", A) if r["actor_id"] == "u-client-a"]
    assert [r["payload"]["detail"]["surface"] for r in reads] == [
        "client_case_view", "client_export.json", "client_export.html"]
    assert all(r["case_id"] == "P5" and r["payload"]["role"] == "CLIENT_VIEWER" for r in reads)


def test_client_cross_tenant_request_is_404_and_access_denied_is_audited(conn, seeded, app_factory):
    case(conn, "PB1", "submitted", tenant=B)
    c = login(TestClient(app_factory()), seeded, "u-client-a")
    for path in ("/client/cases/PB1", "/client/cases/PB1/export.json", "/client/cases/NOPE"):
        assert c.get(path).status_code == 404
    denied = _events(conn, "ACCESS_DENIED")
    assert [d["payload"]["requested_case"] for d in denied] == ["PB1", "PB1", "NOPE"]
    assert all(d["tenant_id"] == A and d["case_id"] is None for d in denied)     # never in B's chain
    assert not [r for r in _events(conn, "CASE_READ", B) if r["actor_id"] == "u-client-a"]


def test_staff_cross_tenant_request_is_audited(conn, seeded, app_factory):
    case(conn, "PA1", "verify")
    c = login(TestClient(app_factory()), seeded, "u-spec-b")
    assert c.get(f"/ops/t/{A}/cases/PA1").status_code == 404
    assert c.get(f"/ops/t/{B}/cases/PA1").status_code == 404           # A's case through B's URL
    denied = _events(conn, "ACCESS_DENIED", "ops")
    assert [(d["payload"]["requested_tenant"], d["payload"]["requested_case"]) for d in denied] == [
        (A, None), (B, "PA1")]


def test_every_client_state_changing_request_is_403_and_audited(conn, seeded, app_factory):
    case(conn, "P6", "verify")
    c = login(TestClient(app_factory()), seeded, "u-client-a")
    tok = csrf_of(c)
    attempts = [("post", f"/ops/t/{A}/cases/P6/actions/approve"), ("post", "/ops/admin/propose"),
                ("post", "/ops/admin/users"), ("post", "/ops/admin/users/u-spec/deactivate"),
                ("post", "/client/cases/P6"), ("post", "/client/upload"), ("put", "/client/cases/P6"),
                ("delete", "/client/cases/P6"), ("patch", f"/ops/t/{A}/cases/P6")]
    for method, path in attempts:
        r = getattr(c, method)(path, **({"data": {"csrf": tok}} if method == "post" else {}))
        assert r.status_code == 403, (method, path, r.status_code)
    denied = _events(conn, "CLIENT_WRITE_DENIED", A)
    assert [(d["payload"]["method"], d["payload"]["path"]) for d in denied] == [
        (m.upper(), p) for m, p in attempts]
    assert conn.execute("SELECT state FROM cases WHERE case_id='P6'").fetchone()["state"] == "DRAFT_READY"
    assert c.post("/logout", follow_redirects=False).status_code == 303          # sign-out still works


# ------------------------------------------------------------------ client export content (R-39)
def _pipeline_case(conn, wanted_state):
    cfg = defaults()
    deps = pipeline.default_deps(MockSystemOfRecord(FIXTURES / "sor_accounts.jsonl"), OfflineLlmClient(), cfg)
    for line in (FIXTURES / "acdvs.jsonl").read_text().splitlines()[:40]:
        env = json.loads(line)
        now = datetime.fromisoformat(env["fixture_meta"]["ingest_date"]).replace(hour=12, tzinfo=timezone.utc)
        res = pipeline.process_dispute(conn, tenant_id=A, dispute=acdv_to_dispute(env), deps=deps, cfg=cfg, now=now)
        conn.commit()
        if res.state == wanted_state:
            yield res.case_id


def test_client_export_has_no_prompts_config_metrics_or_other_tenants(conn, seeded, app_factory, sink):
    approved = None
    for cid in _pipeline_case(conn, "DRAFT_READY"):
        act.open_case(conn, tenant_id=A, case_id=cid, actor=actor("u-spec"))
        try:
            act.approve(conn, tenant_id=A, case_id=cid, actor=actor("u-spec"), sink=sink)
        except act.ActionError:
            continue
        conn.commit()
        if conn.execute("SELECT state FROM cases WHERE case_id = %s", (cid,)).fetchone()["state"] == "SUBMITTED_STUB":
            approved = cid
            break
    assert approved, "no fixture case could be approved without edits"
    case(conn, "PB2", "submitted", tenant=B)
    c = login(TestClient(app_factory()), seeded, "u-client-a")
    body = c.get(f"/client/cases/{approved}/export.json").text
    ex = json.loads(body)
    assert any(e["event_type"] == "MODEL_CALL" for e in ex["timeline"])          # model IDs + hashes (R-22)
    prompts = Path_prompts()
    for f in prompts:
        lines = [x.strip() for x in f.read_text(encoding="utf-8").splitlines() if len(x.strip()) > 40]
        assert not any(x in body for x in lines[:20]), f"prompt text from {f.name} in client export"
    for forbidden in (B, "PB2", "session_idle_timeout_min", "config_versions", "active_seconds", "first_viewed",
                      "staff_tenant_access", "password", "totp"):
        assert forbidden not in body, forbidden
    assert ex["masked"] is True and "SYNACCT" not in body


def Path_prompts():
    from pathlib import Path
    return sorted((Path(__file__).resolve().parents[1] / "prompts").glob("*.md"))


# ------------------------------------------------------------------ domain types adopted
def test_review_records_use_domain_type_and_flat_storage(conn, seeded, sink):
    case(conn, "R1", "submitted")
    sup = actor("u-sup1")
    act.reopen_submitted(conn, tenant_id=A, case_id="R1", actor=sup, reason_code="OTHER",
                         reason_text="hardening test reopen after submission")
    conn.commit()
    b = cd.load_bundle(conn, tenant_id=A, case_id="R1")
    raw = b.reviews[-1]["data"]
    assert raw["action"] == ReviewAction.REOPEN_AFTER_SUBMISSION.value == act.REOPEN
    assert "extra" not in raw and raw["package_version_reopened"] == 1           # flat, as before
    rec = cd.review_from_json(raw)
    assert isinstance(rec, ReviewRecord) and rec.actor_role == Role.SUPERVISOR
    assert rec.extra["package_version_reopened"] == 1
    # compatibility read of a nested form and of an older flat record
    nested = {**{k: raw[k] for k in ("action", "actor_id", "actor_role", "actor_name", "from_state", "to_state")},
              "extra": {"stage": "first"}}
    assert cd.review_from_json(nested).extra == {"stage": "first"}
    assert cd.review_to_json(cd.review_from_json(raw)) == {k: v for k, v in raw.items()}


def test_reviewer_narrative_is_a_human_authored_draft(conn, seeded):
    case(conn, "R2", "verify")
    spec = actor("u-spec")
    act.open_case(conn, tenant_id=A, case_id="R2", actor=spec)
    act.edit(conn, tenant_id=A, case_id="R2", actor=spec, reason_code="NARRATIVE_EDIT_ONLY",
             reason_text="clearer wording for the bureau", narrative="We verified the account. It is accurate.")
    conn.commit()
    d = cd.load_bundle(conn, tenant_id=A, case_id="R2").drafts[-1]["data"]
    assert d["human_authored"] is True and {s["source"] for s in d["sentences"]} == {"HUMAN"}
    assert set(d) == {"sentences", "validator_errors", "attempts", "valid", "template_library_version",
                      "human_authored"}


def test_pipeline_records_llm_suspicious_on_the_classification(conn, tenant):
    """Classification.llm_suspicious mirrors the model's R-14 flag raised during classify."""
    from dataclasses import replace
    cfg = defaults()
    deps = pipeline.default_deps(MockSystemOfRecord(FIXTURES / "sor_accounts.jsonl"), OfflineLlmClient(), cfg)
    real = deps.classify

    def flagging_classify(d, budget):
        out = real(d, budget)
        if d.control_number.endswith(("1", "3", "5", "7", "9")):
            budget.flag_suspicious("classify", "test: model flagged suspicious content")
        return out
    deps = replace(deps, classify=flagging_classify)
    want = {}
    for line in (FIXTURES / "acdvs.jsonl").read_text().splitlines()[:12]:
        env = json.loads(line)
        d = acdv_to_dispute(env)
        now = datetime.fromisoformat(env["fixture_meta"]["ingest_date"]).replace(hour=12, tzinfo=timezone.utc)
        res = pipeline.process_dispute(conn, tenant_id=A, dispute=d, deps=deps, cfg=cfg, now=now)
        if res.case_id:
            want[res.case_id] = d.control_number.endswith(("1", "3", "5", "7", "9"))
    rows = {r["case_id"]: r["data"]["llm_suspicious"] for r in conn.execute(
        "SELECT case_id, data FROM case_artifacts WHERE kind = 'classification'").fetchall()}
    assert rows and {k: want[k] for k in rows} == rows and True in rows.values() and False in rows.values()


def test_client_sees_client_facing_statuses(conn, seeded, app_factory):
    """PRD v1.3 §6.1 Q11 mapping; the audit export keeps internal states."""
    assert portal.client_status("INVESTIGATING") == ("Received", None)
    assert portal.client_status("ESCALATED", ["EVIDENCE_CONFLICT"]) == (
        "In review", "Escalated to a supervisor: evidence conflict")
    assert portal.client_status("SUBMITTED_STUB")[0] == "Response ready (not sent)"
    assert portal.client_status("OUT_OF_SCOPE")[0] == "Out of scope: returned to you"
    case(conn, "S1", "fraud")
    case(conn, "S2", "submitted")
    c = login(TestClient(app_factory()), seeded, "u-client-a")
    page = c.get("/client").text
    assert "Escalated to a supervisor: possible identity fraud" in page and "Response ready (not sent)" in page
    assert "Submitted (stub)" not in page
    case_page = c.get("/client/cases/S2").text
    assert "Response ready (not sent)" in case_page and "Submitted (stub)" not in case_page
    assert json.loads(c.get("/client/cases/S2/export.json").text)["case"]["state"] == "SUBMITTED_STUB"
