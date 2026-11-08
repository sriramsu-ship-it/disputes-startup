"""HTTP tests: R-16 queue + case view, R-17 actions via forms, R-22 export, R-24 metrics, R-21 admin,
client portal isolation (R-27 masking)."""
from __future__ import annotations

import json
import re
import time

import pytest
from fastapi.testclient import TestClient

from disputes.db import repo
from disputes.web import actions as act
from disputes.web import demo
from test_web_support import A, B, actor, app_factory, case, csrf_of, login, seeded  # noqa: F401

Q = "/ops/t/synthetic-tenant-0"


@pytest.fixture
def staff(seeded, app_factory):
    return login(TestClient(app_factory()), seeded, "u-spec")


def queue_ids(html: str) -> list[str]:
    return re.findall(r'<tr class="[^"]*" data-case-id="([^"]+)"', html)


# ------------------------------------------------------------------ R-16 queue
def test_queue_order_and_filters(conn, staff):
    from datetime import date, timedelta
    today = date.today()
    case(conn, "C-LATE-TARGET", "verify", received=today - timedelta(days=2), due=today + timedelta(days=28))
    case(conn, "C-EARLY-TARGET", "verify", received=today - timedelta(days=10), due=today + timedelta(days=20))
    case(conn, "C-AT-RISK", "at_risk")
    case(conn, "C-FRAUD", "fraud")
    case(conn, "C-DONE", "out_of_scope")
    case(conn, "C-OTHER-TENANT", "verify", tenant=B)
    ids = queue_ids(staff.get(f"{Q}/queue").text)
    assert ids == ["C-FRAUD", "C-AT-RISK", "C-EARLY-TARGET", "C-LATE-TARGET"]     # open only, B excluded
    every = queue_ids(staff.get(f"{Q}/queue?state=ALL").text)
    assert "C-DONE" in every and "C-OTHER-TENANT" not in every and every[0] == "C-FRAUD"
    assert queue_ids(staff.get(f"{Q}/queue?state=ESCALATED").text) == ["C-FRAUD"]
    assert queue_ids(staff.get(f"{Q}/queue?flag=ID_FRAUD_SUSPECTED").text) == ["C-FRAUD"]
    html = staff.get(f"{Q}/queue").text
    assert "Synthetic data" in html and "ID fraud suspected" in html


# ------------------------------------------------------------------ case view
def test_case_view_shows_everything_the_reviewer_needs(conn, staff):
    case(conn, "C-PRIOR", "verify")
    case(conn, "C1", "verify")
    repo.update_case_fields(conn, tenant_id=A, case_id="C1", repeat_of_case_id="C-PRIOR")
    conn.commit()
    t0 = time.perf_counter()
    r = staff.get(f"{Q}/cases/C1")
    elapsed = time.perf_counter() - t0
    assert r.status_code == 200 and elapsed < 2.0                                  # R-28 view <= 2 s
    h = r.text
    assert "Synthetic data" in h
    assert 'data-testid="case-state">In review' in h                               # opening moved it
    assert "CONSUMER STATES NEVER LATE FEB 2026" in h                             # ACDV free text
    assert '<mark id="q-C1" title="Claim C1">My February 2026 payment was made on time.</mark>' in h
    assert 'id="ev-EV-CYCLE-2026-02"' in h and "days_past_due" in h               # evidence side by side
    assert 'data-testid="comparison"' in h and "2026-02" in h                     # per-month comparison
    assert 'data-testid="claims"' in h and "Contradicted" in h                    # claim map
    assert "src-chip-LLM" in h and "src-chip-TEMPLATE" in h and "T-VERIFY-1" in h  # sentence sources
    assert "R-10.VERIFY" in h                                                     # R-29 rule ID
    assert 'href="/ops/t/synthetic-tenant-0/cases/C-PRIOR"' in h                  # prior linked case
    assert "Internal target" in h and "ruler" in h                                # deadline / clock


def test_case_view_escalations_and_flags(conn, staff, seeded, app_factory):
    case(conn, "C-F", "fraud")
    case(conn, "C-H", "high")
    case(conn, "C-U", "unaddressed")
    h = staff.get(f"{Q}/cases/C-F").text
    assert "ID_FRAUD_SUSPECTED" in h and "R-07.ID_FRAUD" in h
    h = staff.get(f"{Q}/cases/C-H").text
    assert "Suspicious-content matches" in h and "INJ-ROLE-MARKER" in h and "second supervisor approval" in h
    sup = login(TestClient(app_factory()), seeded, "u-sup1")
    h = sup.get(f"{Q}/cases/C-U").text
    assert "UNADDRESSED_CLAIM" in h and "R-11.UNADDRESSED_CLAIM" in h and "Needs a finding" in h
    assert "Take for review" in h


def test_untrusted_text_is_escaped(conn, staff):
    case(conn, "C1", "verify")
    conn.execute("UPDATE attachments SET extracted_text = extracted_text || %s WHERE case_id = 'C1'",
                 ("\n<script>alert('x')</script><img src=x onerror=alert(1)>",))
    conn.commit()
    h = staff.get(f"{Q}/cases/C1").text
    assert "<script>alert" not in h and "<img src=x" not in h
    assert "&lt;script&gt;alert" in h
    r = staff.get(f"{Q}/cases/C1")
    assert "script-src 'self'" in r.headers["content-security-policy"]


def test_case_of_other_tenant_or_unknown_is_404(conn, staff):
    case(conn, "CB", "verify", tenant=B)
    assert staff.get(f"{Q}/cases/CB").status_code == 404                           # wrong tenant in URL
    assert staff.get(f"{Q}/cases/NOPE").status_code == 404
    assert staff.get("/ops/t/synthetic-tenant-1/cases/CB").status_code == 200       # staff has B access


# ------------------------------------------------------------------ actions over HTTP
def test_edit_without_reason_code_names_the_field(conn, staff):
    case(conn, "C1", "verify")
    staff.get(f"{Q}/cases/C1")
    r = staff.post(f"{Q}/cases/C1/actions/edit", data={"csrf": csrf_of(staff), "outcome": "MODIFY",
                                                      "corr_month_1": "2026-02", "corr_corrected_1": "0",
                                                      "reason_text": "long enough explanation"})
    assert r.status_code == 400 and "reason_code" in r.text and 'data-testid="action-error"' in r.text


def test_full_review_flow_over_http(conn, staff, seeded, app_factory):
    case(conn, "C1", "verify")
    staff.get(f"{Q}/cases/C1")
    tok = csrf_of(staff)
    r = staff.post(f"{Q}/cases/C1/actions/edit", follow_redirects=False, data={
        "csrf": tok, "outcome": "DELETE", "reason_code": "DATA_UNVERIFIABLE",
        "reason_text": "Cannot verify the account history.", "narrative": "We deleted the tradeline.",
        "corr_month_1": "", "corr_corrected_1": ""})
    assert r.status_code == 303
    r = staff.post(f"{Q}/cases/C1/actions/approve", data={"csrf": tok}, follow_redirects=False)
    assert r.status_code == 303
    assert repo.get_case(conn, tenant_id=A, case_id="C1")["state"] == "AWAITING_SECOND_APPROVAL"
    sup1 = login(TestClient(app_factory()), seeded, "u-sup1")
    h = sup1.get(f"{Q}/cases/C1").text
    assert "Give second approval" in h
    r = sup1.post(f"{Q}/cases/C1/actions/second_approve", data={"csrf": csrf_of(sup1)}, follow_redirects=False)
    assert r.status_code == 303
    conn.rollback()
    row = repo.get_case(conn, tenant_id=A, case_id="C1")
    assert row["state"] == "SUBMITTED_STUB" and row["final_outcome"] == "DELETE"
    h = sup1.get(f"{Q}/cases/C1").text
    assert 'data-testid="package"' in h and "Pat Iverson" in h


def test_second_approval_by_editor_is_403_over_http(conn, seeded, app_factory, sink=None):
    case(conn, "C1", "verify")
    sup1 = login(TestClient(app_factory()), seeded, "u-sup1")
    sup1.get(f"{Q}/cases/C1")
    tok = csrf_of(sup1)
    sup1.post(f"{Q}/cases/C1/actions/edit", data={"csrf": tok, "outcome": "DELETE", "reason_code": "OTHER",
                                                  "reason_text": "Consumer evidence is persuasive.",
                                                  "narrative": "We deleted the tradeline."})
    sup1.post(f"{Q}/cases/C1/actions/approve", data={"csrf": tok})
    r = sup1.post(f"{Q}/cases/C1/actions/second_approve", data={"csrf": tok})
    assert r.status_code == 403 and "separation of duties" in r.text


def test_stale_form_gets_409(conn, staff):
    case(conn, "C1", "verify")
    staff.get(f"{Q}/cases/C1")
    r = staff.post(f"{Q}/cases/C1/actions/approve", data={"csrf": csrf_of(staff), "version": "1"})
    assert r.status_code == 409


# ------------------------------------------------------------------ R-22 export
R22_KEYS = {"dispute_as_received", "deadline", "timeline", "evidence", "attachments", "comparison", "claims",
            "drafts", "reviews", "packages", "versions", "reference_tables", "hash_chain", "decision"}


def test_export_json_and_html_for_staff(conn, seeded, app_factory):
    case(conn, "C1", "submitted")
    aud = login(TestClient(app_factory()), seeded, "u-aud")
    t0 = time.perf_counter()
    r = aud.get(f"{Q}/cases/C1/export.json")
    assert r.status_code == 200 and time.perf_counter() - t0 < 10
    ex = json.loads(r.text)
    assert R22_KEYS <= set(ex)
    assert ex["hash_chain"]["ok"] is True and ex["hash_chain"]["status"] == "verified"
    assert ex["case"]["account_number"].startswith("SYNACCT")                     # staff see full data
    assert ex["attachments"][0]["sha256"] and ex["evidence"][0]["sha256"]
    assert ex["packages"][0]["dfAuthorizedName"] == "Sam Okafor (SYNTHETIC)"
    assert {s["source"] for s in ex["drafts"][0]["sentences"]} == {"LLM", "TEMPLATE"}
    assert ex["reviews"][0]["action"] == "APPROVE"
    assert "payment_rating_map" in ex["reference_tables"]
    assert ex["versions"]["rules_version"] == "1.0.0"
    h = aud.get(f"{Q}/cases/C1/export.html").text
    assert "Audit hash chain: <strong>verified</strong>" in h and "Synthetic data" in h
    for section in ("Dispute as received", "Timeline", "Evidence", "Attachments", "Month by month",
                    "Claims, quotes and findings", "Draft versions", "Reviewer decisions", "Response packages",
                    "Reference tables"):
        assert section in h
    reads = [e for e in repo.audit_events_for_case(conn, tenant_id=A, case_id="C1") if e["event_type"] == "CASE_READ"]
    assert len(reads) == 2 and all(e["actor_id"] == "u-aud" for e in reads)       # R-21 auditor reads


def test_export_reports_a_broken_chain(conn, seeded, app_factory):
    case(conn, "C1", "submitted")
    conn.execute("ALTER TABLE audit_events DISABLE TRIGGER USER")
    conn.execute("UPDATE audit_events SET payload = '{\"tampered\": true}'::jsonb WHERE event_id = "
                 "(SELECT min(event_id) FROM audit_events WHERE case_id = 'C1')")
    conn.execute("ALTER TABLE audit_events ENABLE TRIGGER USER")
    conn.commit()
    staff = login(TestClient(app_factory()), seeded, "u-spec")
    ex = staff.get(f"{Q}/cases/C1/export.json").json()
    assert ex["hash_chain"]["ok"] is False and ex["hash_chain"]["status"] == "BROKEN"
    assert ex["hash_chain"]["first_broken_event_id"] is not None


# ------------------------------------------------------------------ client portal isolation
def test_client_portal_is_own_tenant_only_and_masked(conn, seeded, app_factory):
    case(conn, "A-OPEN", "verify")
    case(conn, "A-DONE", "submitted")
    case(conn, "B-DONE", "submitted", tenant=B)
    ca = login(TestClient(app_factory()), seeded, "u-client-a")
    h = ca.get("/client").text
    assert "A-OPEN" in h and "A-DONE" in h and "B-DONE" not in h
    assert "SYNACCT" not in h and "••••" in h                                    # last 4 only
    assert 'data-testid="sla"' in h and "Verified as reported" in h
    assert ca.get("/client/cases/B-DONE").status_code == 404
    assert ca.get("/client/cases/B-DONE/export.json").status_code == 404
    assert ca.get("/client/cases/A-OPEN/export.json").status_code == 404           # not completed yet
    tl = ca.get("/client/cases/A-DONE").text
    assert 'data-testid="client-timeline"' in tl and "Submitted (stub)" in tl and "u-spec" not in tl
    ex = ca.get("/client/cases/A-DONE/export.json").json()
    assert ex["masked"] is True and R22_KEYS <= set(ex)
    blob = json.dumps(ex)
    acct = repo.get_case(conn, tenant_id=A, case_id="A-DONE")["account_number"]
    assert acct not in blob and "Testcombe" not in blob and "905-00" not in blob
    assert ca.get("/client/cases/A-DONE/export.html").status_code == 200
    cb = login(TestClient(app_factory()), seeded, "u-client-b")
    assert cb.get("/client/cases/A-DONE").status_code == 404
    assert "B-DONE" in cb.get("/client").text


def test_client_dashboard_counts(conn, seeded, app_factory):
    case(conn, "A1", "verify")
    case(conn, "A2", "at_risk")
    case(conn, "A3", "breached")
    case(conn, "A4", "out_of_scope")
    from disputes.web import portal
    d = portal.dashboard(conn, tenant_id=A)
    assert d["sla"] == {"ON_TRACK": 1, "AT_RISK": 1, "BREACHED": 1}
    assert d["total"] == 4 and d["completed"] == 1 and d["by_outcome"] == {"OUT_OF_SCOPE": 1}
    assert portal.dashboard(conn, tenant_id=B)["total"] == 0


# ------------------------------------------------------------------ R-24 metrics
def test_active_seconds_beacon_and_csv(conn, seeded, app_factory):
    case(conn, "C1", "verify")
    spec = login(TestClient(app_factory()), seeded, "u-spec")
    spec.get(f"{Q}/cases/C1")
    r = spec.post(f"{Q}/cases/C1/metrics", json={"active_seconds": 42, "csrf": csrf_of(spec)})
    assert r.json()["stored_seconds"] == 42
    assert spec.post(f"{Q}/cases/C1/metrics", json={"active_seconds": 99999,
                                                    "csrf": csrf_of(spec)}).json()["stored_seconds"] == 300
    assert spec.post(f"{Q}/cases/C1/metrics", json={"active_seconds": 5}).status_code == 403   # no CSRF
    spec.post(f"{Q}/cases/C1/actions/approve", data={"csrf": csrf_of(spec)})
    sup = login(TestClient(app_factory()), seeded, "u-sup1")
    r = sup.get(f"{Q}/metrics.csv")
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/csv")
    lines = r.text.strip().splitlines()
    assert lines[0].startswith("case_id,state,opened_count,first_viewed_at,active_review_seconds")
    row = next(x for x in lines if x.startswith("C1,"))
    assert ",342.0," in row and ",APPROVE,no," in row and "SUBMITTED_STUB" in row


# ------------------------------------------------------------------ R-21 admin config
def test_config_change_needs_a_second_admin_and_is_audited(conn, seeded, app_factory):
    a1 = login(TestClient(app_factory()), seeded, "u-admin")
    tok = csrf_of(a1)
    r = a1.post("/ops/admin/propose", data={"csrf": tok, "key": "internal_target_business_days_before_due",
                                            "value": "4", "reason": "short"})
    assert r.status_code == 400
    r = a1.post("/ops/admin/propose", data={"csrf": tok, "key": "mode", "value": "live",
                                            "reason": "trying to go live from the UI"})
    assert r.status_code == 400 and "cannot be changed" in r.text
    r = a1.post("/ops/admin/propose", data={"csrf": tok, "key": "internal_target_business_days_before_due",
                                            "value": "4", "reason": "Client asked for a bigger buffer."})
    assert r.status_code == 200 and 'data-testid="pending"' in r.text
    req = conn.execute("SELECT request_id FROM config_change_requests").fetchone()["request_id"]
    r = a1.post(f"/ops/admin/requests/{req}", data={"csrf": tok, "decision": "approve"})
    assert r.status_code == 403 and "your own config change" in r.text
    from disputes.web.configsvc import effective_config
    assert effective_config(conn).internal_target_business_days_before_due == 3
    sup = login(TestClient(app_factory()), seeded, "u-sup1")
    assert sup.post(f"/ops/admin/requests/{req}", data={"csrf": csrf_of(sup), "decision": "approve"}).status_code == 403
    a2 = login(TestClient(app_factory()), seeded, "u-admin2")
    r = a2.post(f"/ops/admin/requests/{req}", data={"csrf": csrf_of(a2), "decision": "approve"})
    assert r.status_code == 200
    conn.rollback()
    assert effective_config(conn).internal_target_business_days_before_due == 4
    ev = conn.execute("SELECT * FROM audit_events WHERE tenant_id = 'ops' AND event_type = 'CONFIG_CHANGED'").fetchone()
    p = ev["payload"]
    assert (p["old_value"], p["new_value"], p["proposed_by"], p["decided_by"]) == (3, 4, "u-admin", "u-admin2")
    assert ev["actor_id"] == "u-admin2" and ev["actor_role"] == "ADMIN" and ev["occurred_at"] is not None
    h = a2.get("/ops/admin").text
    assert "v1 by u-admin" in h


def test_demo_seed_refuses_live_mode(conn, seeded):
    conn.execute("INSERT INTO config_versions (tenant_id, key, value, version, changed_by, reason) "
                 "VALUES ('ops','mode','\"live\"'::jsonb,1,'u-admin','test live refusal')")
    with pytest.raises(RuntimeError):
        demo.make_case(conn, tenant_id=A, case_id="X", scenario="verify")


def test_package_receipt_matches_sink(conn, seeded):
    from disputes.contracts_bridge import StubResponseSink
    sink = StubResponseSink()
    case(conn, "C1", "verify")
    act.open_case(conn, tenant_id=A, case_id="C1", actor=actor("u-spec"))
    act.approve(conn, tenant_id=A, case_id="C1", actor=actor("u-spec"), sink=sink)
    from disputes.audit.chain import canonical, sha256_hex
    pkg = repo.latest_artifact(conn, tenant_id=A, case_id="C1", kind="package")["data"]
    assert pkg["sink_receipt"] == sha256_hex(canonical(sink.packages[0]))
