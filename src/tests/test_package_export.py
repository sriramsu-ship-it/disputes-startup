"""R-20 package and R-22 export against a real database. Data is SYNTHETIC.

- G5 (PRD §3): for sampled cases, parse ONLY the rendered export HTML (no DB access while reading)
  and recover outcome, rule ID and version, evidence IDs and each claim's finding; they must equal
  the stored values. Cases come from the real pipeline (offline agents, committed fixtures) plus the
  web demo scenarios that reach approval, second approval, reopen and out-of-scope.
- Client copy (R-39/R-41): own case only, masked, no staff names, no event payloads, no pattern IDs,
  hashes unchanged.
- Timing (R-22): export JSON + HTML + PDF + zip <= 10 s for a case with 10 attachments.
"""
from __future__ import annotations

import io
import json
import random
import time
import zipfile
from datetime import datetime, timezone

import pytest

from disputes.audit.chain import sha256_hex
from disputes.contracts_bridge import StubResponseSink
from disputes.db import repo
from disputes.domain import ArtifactKind, CaseState
from disputes.package import bundle, pdf, render
from disputes.package.build import PACKAGE_SCHEMA_VERSION
from disputes.web import actions as act
from disputes.web import casedata as cd
from disputes.web import export
from disputes.web import package_routes as pr
from test_package_support import body_rows, parse_by_id
from test_web_support import A, B, actor, case, seeded  # noqa: F401

HAS_PDF = pdf.available()


def _approve(conn, cid, who="u-spec", tenant=A):
    a = actor(who)
    act.open_case(conn, tenant_id=tenant, case_id=cid, actor=a)
    act.approve(conn, tenant_id=tenant, case_id=cid, actor=a, sink=StubResponseSink())
    conn.commit()


# ------------------------------------------------------------------ package versions (R-20)
def test_delete_with_second_approval_then_reopen_writes_v2_and_both_verify(conn, seeded):
    case(conn, "M1", "modify")
    _approve(conn, "M1")
    act.reopen_submitted(conn, tenant_id=A, case_id="M1", actor=actor("u-sup1"), reason_code="DATA_UNVERIFIABLE",
                         reason_text="The archive record for February cannot be verified.")
    act.edit(conn, tenant_id=A, case_id="M1", actor=actor("u-sup1"), reason_code="DATA_UNVERIFIABLE",
             reason_text="Cannot verify February 2026 from the archive.", outcome="DELETE", corrections=[],
             narrative="We are deleting the disputed tradeline because the February 2026 record cannot be verified.",
             claim_findings=None)
    act.approve(conn, tenant_id=A, case_id="M1", actor=actor("u-sup1"), sink=StubResponseSink())
    act.second_approve(conn, tenant_id=A, case_id="M1", actor=actor("u-sup2"), sink=StubResponseSink())
    conn.commit()
    rows = repo.artifact_history(conn, tenant_id=A, case_id="M1", kind=ArtifactKind.PACKAGE)
    v1, v2 = rows[0]["data"], rows[1]["data"]
    assert v1["package_schema_version"] == v2["package_schema_version"] == PACKAGE_SCHEMA_VERSION
    assert v1["outcome"] == "MODIFY" and v1["month_by_month"][0]["changed"] is True
    assert v1["month_by_month"][0]["reported"] == "2" and v1["month_by_month"][0]["response_value"] == "1"
    assert v2["outcome"] == "DELETE" and v2["supersedes_package_sha256"] == rows[0]["data_sha256"]
    assert v2["change_reason"]["reason_code"] == "DATA_UNVERIFIABLE"
    assert [a["stage"] for a in v2["approvals"]] == ["first", "second"] and all(a["at"] for a in v2["approvals"])
    assert v2["dfAuthorizedName"] == "Rene Castillo (SYNTHETIC)"
    ex = export.build_export(conn, tenant_id=A, case_id="M1")
    assert [p["ok"] for p in ex["package_integrity"]] == [True, True]
    assert ex["summary"]["decided"]["final_outcome"] == "DELETE" and ex["summary"]["decided"]["departs_from_proposal"]
    html = render.render_package_html(pr.package_docs(conn, tenant_id=A, case_id="M1", masked=False)[1], masked=False)
    assert "SYNTHETIC DEMONSTRATION" in html and "not been validated" in html and "Second approval (R-19)" in html
    assert "Rene Castillo (SYNTHETIC)" in html and "SYNACCT" not in html          # rendered account is last 4


def test_tampered_package_is_reported_in_the_export(conn, seeded):
    case(conn, "T1", "submitted")
    conn.execute("ALTER TABLE case_artifacts DISABLE TRIGGER USER")
    conn.execute("UPDATE case_artifacts SET data = jsonb_set(data, '{outcome}', '\"DELETE\"') "
                 "WHERE case_id = 'T1' AND kind = 'package'")
    conn.execute("ALTER TABLE case_artifacts ENABLE TRIGGER USER")
    conn.commit()
    ex = export.build_export(conn, tenant_id=A, case_id="T1")
    assert ex["package_integrity"][0]["ok"] is False
    html = render.render_export_html(ex)
    assert "DO NOT match" in html


# ------------------------------------------------------------------ G5: the export alone answers the questions
def _pipeline_cases(conn, n_fixtures=40):
    from disputes.agents.llm import OfflineLlmClient
    from disputes.config import defaults
    from disputes.contracts_bridge import MockSystemOfRecord, acdv_to_dispute
    from disputes.workflow import pipeline
    from test_agents_helpers import FIXTURES
    cfg = defaults()
    deps = pipeline.default_deps(MockSystemOfRecord(FIXTURES / "sor_accounts.jsonl"), OfflineLlmClient(), cfg)
    envs = [json.loads(x) for x in (FIXTURES / "acdvs.jsonl").read_text().splitlines() if x.strip()][:n_fixtures]
    ids = []
    for env in sorted(envs, key=lambda e: e["fixture_meta"]["ingest_date"]):
        now = datetime.fromisoformat(env["fixture_meta"]["ingest_date"]).replace(hour=12, tzinfo=timezone.utc)
        res = pipeline.process_dispute(conn, tenant_id=A, dispute=acdv_to_dispute(env, tenant_id=A), deps=deps,
                                       cfg=cfg, now=now)
        if res.case_id:
            ids.append(res.case_id)
    conn.commit()
    return ids


def _stored_values(conn, cid):
    b = cd.load_bundle(conn, tenant_id=A, case_id=cid)
    d = b.get(ArtifactKind.DECISION) or {}
    return {
        "final": b.case.get("final_outcome") or "NONE",
        "proposed": b.case.get("proposed_outcome") or "NONE",
        "rules": sorted((f["rule_id"], f["rule_version"]) for f in d.get("firings") or []),
        "evidence": sorted([e["evidence_id"] for e in b.evidence] + [a["attachment_id"] for a in b.attachments]),
        "claims": {c["claim_id"]: c.get("finding") or "NONE" for c in cd.effective_claims(b)},
    }


def _read_export_html(html: str) -> dict:
    text, rows = parse_by_id(html)
    return {
        "final": text["g5-final-outcome"], "proposed": text["g5-proposed-outcome"],
        "rules": sorted((r[0], r[1]) for r in body_rows(rows["g5-rules"]) if len(r) == 4),
        "evidence": sorted(r[0] for r in body_rows(rows["g5-evidence"]) if len(r) == 4),
        "claims": {r[0].split()[0]: r[1].split()[-1] for r in body_rows(rows["g5-claims"]) if len(r) == 4},
    }


def test_g5_sampled_cases_are_reconstructable_from_the_rendered_export_alone(conn, seeded):
    ids = _pipeline_cases(conn)
    ready = [i for i in ids if repo.get_case(conn, tenant_id=A, case_id=i)["state"] == CaseState.DRAFT_READY.value]
    for cid in ready[:4]:                                   # approve some so final outcomes and packages exist
        b = cd.load_bundle(conn, tenant_id=A, case_id=cid)
        if not cd.approval_blockers(b, narrative_max_words=10_000):
            _approve(conn, cid)
    for cid, sc in (("W-MOD", "modify"), ("W-OOS", "out_of_scope"), ("W-UNADDR", "unaddressed"),
                    ("W-FRAUD", "fraud"), ("W-HIGH", "high")):
        case(conn, cid, sc)
    _approve(conn, "W-MOD")
    act.open_case(conn, tenant_id=A, case_id="W-HIGH", actor=actor("u-spec"))
    act.approve(conn, tenant_id=A, case_id="W-HIGH", actor=actor("u-spec"), sink=StubResponseSink())
    act.second_approve(conn, tenant_id=A, case_id="W-HIGH", actor=actor("u-sup1"), sink=StubResponseSink())
    conn.commit()
    pool = sorted(set(ids))
    sample = random.Random(20261115).sample(pool, 10) + ["W-MOD", "W-OOS", "W-UNADDR", "W-FRAUD", "W-HIGH"] \
        + [c for c in ready[:4]]
    checked, kinds = 0, set()
    for cid in dict.fromkeys(sample):
        html = render.render_export_html(export.build_export(conn, tenant_id=A, case_id=cid))
        got = _read_export_html(html)                          # from here on: only the rendered HTML
        want = _stored_values(conn, cid)
        assert got == want, cid
        checked += 1
        kinds.add((want["final"], want["proposed"]))
    assert checked >= 15 and len(kinds) >= 4                  # a mix of outcomes, not one kind repeated


# ------------------------------------------------------------------ client copy (R-39, R-41, R-27)
def test_client_copy_is_masked_and_holds_nothing_beyond_r22(conn, seeded):
    case(conn, "A-H", "high")
    act.open_case(conn, tenant_id=A, case_id="A-H", actor=actor("u-spec"))
    act.approve(conn, tenant_id=A, case_id="A-H", actor=actor("u-spec"), sink=StubResponseSink())
    act.second_approve(conn, tenant_id=A, case_id="A-H", actor=actor("u-sup1"), sink=StubResponseSink())
    case(conn, "B-X", "submitted", tenant=B)
    conn.commit()
    staff = export.build_export(conn, tenant_id=A, case_id="A-H")
    cl = export.build_export(conn, tenant_id=A, case_id="A-H", masked=True)
    blob = json.dumps(cl, ensure_ascii=False)
    acct = repo.get_case(conn, tenant_id=A, case_id="A-H")["account_number"]
    other = repo.get_case(conn, tenant_id=B, case_id="B-X")
    assert acct not in blob and acct[-4:] in blob and "Testcombe" not in blob
    assert other["account_number"] not in blob and B not in blob and "B-X" not in blob    # no other tenant
    for name in ("Sam Okafor", "Pat Iverson", "Rene Castillo", "Dana Whitfield"):       # staff names (Q16)
        assert name not in blob
    assert "staff u-sup1 (SUPERVISOR)" in blob
    assert all(e["payload"] == "omitted in client copy" for e in cl["timeline"])
    assert "INJ-ROLE-MARKER" not in blob and cl["suspicion"]["matches"] == 1 and cl["suspicion"]["level"] == "HIGH"
    assert "active_seconds" not in blob and "case_metrics" not in blob                    # no per-analyst metrics
    # hashes survive masking unchanged (they refer to the originals)
    assert [e["sha256"] for e in cl["evidence"]] == [e["sha256"] for e in staff["evidence"]]
    assert [p["sha256"] for p in cl["packages"]] == [p["sha256"] for p in staff["packages"]]
    assert [e["case_hash"] for e in cl["timeline"]] == [e["case_hash"] for e in staff["timeline"][:len(cl["timeline"])]]
    assert cl["package_integrity"][0]["ok"] is True and cl["summary"]["trust"]["packages"][0]["ok"] is True
    html = render.render_export_html(cl)
    assert "client copy" in html and "Pat Iverson" not in html and acct not in html
    docs = pr.package_docs(conn, tenant_id=A, case_id="A-H", masked=True)
    ph = render.render_package_html(docs[0], masked=True)
    assert docs[0]["integrity"]["ok"] and "withheld in client copy" in ph and "Sam Okafor" not in ph
    assert acct not in json.dumps(docs[0]["pkg"]) and docs[0]["pkg"]["account_number"] == "••••" + acct[-4:]


# ------------------------------------------------------------------ bundle and timing (R-22)
def _ten_attachments(conn, cid):
    for i in range(2, 11):
        text = f"Synthetic attachment {i}. " * 200
        repo.insert_attachment(conn, tenant_id=A, case_id=cid, att={
            "attachment_id": f"A{i}", "file_name": "../../evil name.txt" if i == 2 else f"statement_{i}.txt",
            "media_type": "text/plain", "page_count": 1, "sha256": sha256_hex(text), "extracted_text": text,
            "metadata": {}})
    conn.commit()


@pytest.mark.parametrize("masked", [False, True])
def test_bundle_contents_and_ten_attachment_case_within_10s(conn, seeded, masked):
    case(conn, "Z1", "submitted")
    _ten_attachments(conn, "Z1")
    t0 = time.perf_counter()
    ex = export.build_export(conn, tenant_id=A, case_id="Z1", masked=masked)
    html = render.render_export_html(ex)
    pdf_bytes = pdf.html_to_pdf(html) if HAS_PDF else None
    z = bundle.build_bundle(ex, package_docs=pr.package_docs(conn, tenant_id=A, case_id="Z1", masked=masked))
    elapsed = time.perf_counter() - t0
    print(f"\n[R-22 timing] masked={masked} 10 attachments: export+html+pdf+zip {elapsed:.2f}s "
          f"(pdf {'yes' if HAS_PDF else 'NO RENDERER'})")
    assert elapsed <= 10.0
    assert len(ex["attachments"]) == 10
    if HAS_PDF:
        assert pdf_bytes.startswith(b"%PDF")
    zf = zipfile.ZipFile(io.BytesIO(z))
    names = set(zf.namelist())
    man = json.loads(zf.read("MANIFEST.json"))
    assert {"README.txt", "export.json", "export.html", "packages/package-v1.json", "packages/package-v1.html"} <= names
    assert ("export.pdf" in names) == HAS_PDF
    att = sorted(n for n in names if n.startswith("attachments/"))
    assert len(att) == 10 and all(".." not in n and n.count("/") == 1 for n in att)
    for f in man["files"]:
        assert sha256_hex(zf.read(f["path"])) == f["sha256"]
    assert all(o["original_included"] is False for o in man["original_attachments"])
    assert "NOT included" in man["original_attachments_note"]
    assert man["masked"] is masked and json.loads(zf.read("export.json"))["content_sha256"] == ex["content_sha256"]
    if masked:
        acct = repo.get_case(conn, tenant_id=A, case_id="Z1")["account_number"]
        assert all(acct.encode() not in zf.read(n) for n in names if not n.endswith(".pdf"))


@pytest.mark.skipif(not HAS_PDF, reason="no headless Chromium on this host")
def test_pdf_has_the_same_text_as_the_html(conn, seeded, tmp_path):
    case(conn, "P1", "submitted")
    ex = export.build_export(conn, tenant_id=A, case_id="P1")
    data = pdf.html_to_pdf(render.render_export_html(ex))
    assert data.startswith(b"%PDF") and len(data) > 10_000
    import shutil
    import subprocess
    if shutil.which("pdftotext"):
        p = tmp_path / "x.pdf"
        p.write_bytes(data)
        txt = subprocess.run(["pdftotext", str(p), "-"], capture_output=True, text=True, timeout=30).stdout
        assert "Case summary" in txt and "SYNTHETIC DEMONSTRATION" in txt and "R-10.VERIFY" in txt


def test_a_case_without_audit_events_is_not_presented_as_trusted(conn, seeded):
    case(conn, "NOEV", "fraud")                       # demo data inserted directly: no audit events
    html = render.render_export_html(export.build_export(conn, tenant_id=A, case_id="NOEV"))
    assert "No audit events are recorded for this case" in html
