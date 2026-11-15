"""HTTP: package document routes, export PDF and zip, for staff and the client portal. SYNTHETIC data."""
from __future__ import annotations

import io
import json
import zipfile

import pytest
from fastapi.testclient import TestClient

from disputes.db import repo
from disputes.package import pdf
from test_web_support import A, B, app_factory, case, login, seeded  # noqa: F401

Q = "/ops/t/synthetic-tenant-0"
HAS_PDF = pdf.available()
R47 = "DEMO · Synthetic data only · Not connected to e-OSCAR or any credit bureau · Never enter real personal information"


def _events(conn, cid, tenant=A, etype="CASE_READ"):
    return [e for e in repo.audit_events_for_case(conn, tenant_id=tenant, case_id=cid) if e["event_type"] == etype]


def test_staff_package_routes_and_export_files(conn, seeded, app_factory):
    case(conn, "C1", "submitted")
    aud = login(TestClient(app_factory()), seeded, "u-aud")
    h = aud.get(f"{Q}/cases/C1/packages/1.html")
    assert h.status_code == 200 and 'data-testid="package-doc"' in h.text
    assert "SYNTHETIC DEMONSTRATION" in h.text and "/static/package.css" in h.text and "<style>" not in h.text
    assert "Verified as reported" in h.text and "Sam Okafor (SYNTHETIC)" in h.text
    assert "Response package: NOT SENT. Synthetic demo." in h.text and "placeholder codes" in h.text
    assert R47 in h.text
    j = aud.get(f"{Q}/cases/C1/packages/1.json")
    assert j.status_code == 200 and json.loads(j.text)["package_schema_version"].startswith("placeholder-")
    assert aud.get(f"{Q}/cases/C1/packages/2.html").status_code == 404
    assert aud.get(f"{Q}/cases/C1/packages/1.exe").status_code == 404
    z = aud.get(f"{Q}/cases/C1/audit-export.zip")
    assert z.status_code == 200 and z.headers["content-type"] == "application/zip"
    assert "MANIFEST.json" in zipfile.ZipFile(io.BytesIO(z.content)).namelist()
    assert aud.get(f"{Q}/cases/C1/audit-export.txt").status_code == 404
    if HAS_PDF:
        p = aud.get(f"{Q}/cases/C1/audit-export.pdf")
        assert p.status_code == 200 and p.content.startswith(b"%PDF")
    surfaces = [e["payload"]["detail"]["surface"] for e in _events(conn, "C1")]
    assert {"package.v1.html", "package.v1.json", "export.zip"} <= set(surfaces)          # R-21 auditor reads
    ex = aud.get(f"{Q}/cases/C1/export.html").text                                         # app's route, my template
    assert R47 in ex and "Case summary" in ex and "audit-export.pdf" in ex and "packages/1.html" in ex


def test_staff_without_tenant_access_and_clients_cannot_use_staff_routes(conn, seeded, app_factory):
    case(conn, "BX", "submitted", tenant=B)
    specb = login(TestClient(app_factory()), seeded, "u-spec-b")
    assert specb.get(f"{Q}/cases/BX/packages/1.html").status_code == 404                  # wrong tenant in URL
    ca = login(TestClient(app_factory()), seeded, "u-client-a")
    assert ca.get(f"{Q}/cases/BX/audit-export.zip").status_code in (403, 404)


def test_client_routes_own_completed_cases_only_masked_and_audited(conn, seeded, app_factory):
    case(conn, "A-DONE", "submitted")
    case(conn, "A-OPEN", "verify")
    case(conn, "B-DONE", "submitted", tenant=B)
    ca = login(TestClient(app_factory()), seeded, "u-client-a")
    acct = repo.get_case(conn, tenant_id=A, case_id="A-DONE")["account_number"]
    h = ca.get("/client/cases/A-DONE/packages/1.html")
    assert h.status_code == 200 and acct not in h.text and "Sam Okafor" not in h.text and "withheld in client copy" in h.text
    j = json.loads(ca.get("/client/cases/A-DONE/packages/1.json").text)
    assert j["account_number"] == "••••" + acct[-4:] and "Sam Okafor" not in json.dumps(j)
    z = ca.get("/client/cases/A-DONE/audit-export.zip")
    zf = zipfile.ZipFile(io.BytesIO(z.content))
    assert json.loads(zf.read("MANIFEST.json"))["audience"] == "client"
    assert all(acct.encode() not in zf.read(n) for n in zf.namelist() if not n.endswith(".pdf"))
    assert ca.get("/client/cases/B-DONE/packages/1.html").status_code == 404              # other tenant
    assert ca.get("/client/cases/B-DONE/audit-export.zip").status_code == 404
    assert ca.get("/client/cases/A-OPEN/audit-export.zip").status_code == 404              # not completed
    assert not _events(conn, "B-DONE", tenant=B)                                            # nothing written to B
    reads = _events(conn, "A-DONE")
    assert {e["payload"]["detail"]["surface"] for e in reads} >= {"package.v1.html", "package.v1.json", "export.zip"}
    assert all(e["actor_id"] == "u-client-a" and e["actor_role"] == "CLIENT_VIEWER" for e in reads)
    ex = ca.get("/client/cases/A-DONE/export.html").text
    assert "/client/cases/A-DONE/audit-export.pdf" in ex and "/ops/" not in ex


def test_pdf_unavailable_answers_503_and_bundle_says_so(conn, seeded, app_factory, monkeypatch):
    monkeypatch.setattr(pdf, "find_browser", lambda: None)
    case(conn, "C1", "submitted")
    staff = login(TestClient(app_factory()), seeded, "u-spec")
    r = staff.get(f"{Q}/cases/C1/audit-export.pdf")
    assert r.status_code == 503 and "Save as PDF" in r.text
    assert staff.get(f"{Q}/cases/C1/packages/1.pdf").status_code == 503
    zf = zipfile.ZipFile(io.BytesIO(staff.get(f"{Q}/cases/C1/audit-export.zip").content))
    man = json.loads(zf.read("MANIFEST.json"))
    assert "export.pdf" not in zf.namelist() and man["not_included"][0]["path"] == "export.pdf"


@pytest.mark.skipif(not HAS_PDF, reason="no headless Chromium on this host")
def test_client_pdf_download(conn, seeded, app_factory):
    case(conn, "A-DONE", "submitted")
    ca = login(TestClient(app_factory()), seeded, "u-client-a")
    for path in ("/client/cases/A-DONE/audit-export.pdf", "/client/cases/A-DONE/packages/1.pdf"):
        r = ca.get(path)
        assert r.status_code == 200 and r.content.startswith(b"%PDF") and "attachment" in r.headers["content-disposition"]
