"""platform-core: job queue (ADR-002), worker, CLI (ingest/work/verify/anchor/seed/backup/restore, R-32)."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import psycopg
import pytest

from disputes import cli
from disputes.audit.verify import verify_all
from disputes.db import repo
from disputes.db.core import connect, ensure_tenant
from disputes.workflow import jobs
from disputes.workflow.worker import run_worker
from test_platform_core_pipeline import CFG, Scenario, make_dispute, run

SRC = Path(__file__).resolve().parents[1]
FIXTURES = SRC / "data" / "fixtures" / "seed20261019_n200"


def _payload(control="CN-1"):
    env = {"fixture_schema_version": "placeholder-acdv-0.1.0", "synthetic": True,
           "fixture_meta": {"ingest_date": "2026-10-10"},
           "acdv": {"synthetic": True, "control_number": control, "cra": "SYNTH-CRA-1",
                    "date_received": "2026-10-09", "response_due_date": "2026-11-05",
                    "account_number": "SYNACCT0001", "consumer": {"first_name": "Test", "last_name": "Person"},
                    "dispute_codes": ["PLH-PH-01"], "disputed_months": ["2026-01"], "free_text": "x",
                    "attachments": []}}
    return {"envelope": env, "sor_path": "/nonexistent", "as_of": "2026-10-10T15:00:00+00:00"}


def _fake_deps_for(sc=None):
    sc = sc or Scenario()
    return lambda tenant_id, payload: sc.deps()


# ---------------------------------------------------------------- queue primitives
def test_claim_skip_locked_lease_complete(conn, tenant, db_url):
    j1 = jobs.enqueue(conn, tenant_id=tenant, kind="process_dispute", payload={"n": 1})
    j2 = jobs.enqueue(conn, tenant_id=tenant, kind="process_dispute", payload={"n": 2})
    other = connect(db_url)
    try:
        with other.transaction():   # another worker holds a row lock on j1 (mid-claim)
            other.execute("SELECT * FROM jobs WHERE job_id = %s FOR UPDATE", (j1,))
            got = jobs.claim(conn)
            assert got["job_id"] == j2          # SKIP LOCKED: not blocked, takes the next one
    finally:
        other.close()
    got1 = jobs.claim(conn)
    assert got1["job_id"] == j1 and got1["status"] == "RUNNING" and got1["attempts"] == 1
    assert got1["locked_until"] is not None
    assert jobs.claim(conn) is None
    assert jobs.complete(conn, got1, case_id=None) and jobs.complete(conn, got, case_id=None)
    assert jobs.counts(conn) == {"DONE": 2}
    assert jobs.next_run_after_s(conn) is None


def test_claim_is_tenant_filtered(conn, tenant):
    ensure_tenant(conn, "synthetic-tenant-1", "Example Auto Finance (SYNTHETIC)")
    conn.commit()
    jobs.enqueue(conn, tenant_id="synthetic-tenant-1", kind="process_dispute", payload={})
    assert jobs.claim(conn, tenant_ids=[tenant]) is None
    assert jobs.claim(conn, tenant_ids=["synthetic-tenant-1"])["tenant_id"] == "synthetic-tenant-1"


def test_fail_backoff_then_dead_letter_escalates_case(conn, tenant):
    # a case still mid-pipeline (CLASSIFIED) that a job keeps failing on
    with conn.transaction():
        conn.execute("INSERT INTO cases (case_id, tenant_id, channel, control_number, state, raw_payload_sha256, "
                     "synthetic) VALUES ('ST0-STUCK', %s, 'ACDV', 'CN-STUCK', 'CLASSIFIED', %s, true)",
                     (tenant, "0" * 64))
    jid = jobs.enqueue(conn, tenant_id=tenant, kind="process_dispute", payload=_payload("CN-STUCK"), max_attempts=2)
    j = jobs.claim(conn)
    assert jobs.fail(conn, j, error="boom 1", backoff_base_s=60) == "QUEUED"
    row = conn.execute("SELECT * FROM jobs WHERE job_id = %s", (jid,)).fetchone()
    assert row["last_error"] == "boom 1" and row["status"] == "QUEUED"
    assert jobs.claim(conn) is None                         # backoff: not claimable yet
    assert 55 <= jobs.next_run_after_s(conn) <= 60
    conn.execute("UPDATE jobs SET run_after = now() WHERE job_id = %s", (jid,))
    conn.commit()
    j = jobs.claim(conn)
    assert j["attempts"] == 2
    assert jobs.fail(conn, j, error="boom 2") == "DEAD"
    case = repo.get_case(conn, tenant_id=tenant, case_id="ST0-STUCK")
    assert case["state"] == "ESCALATED"
    evs = conn.execute("SELECT * FROM audit_events WHERE event_type = 'JOB_DEAD_LETTERED'").fetchall()
    assert len(evs) == 1 and evs[0]["case_id"] == "ST0-STUCK" and evs[0]["payload"]["case_escalated"]
    sc = [e for e in repo.audit_events_for_case(conn, tenant_id=tenant, case_id="ST0-STUCK")
          if e["event_type"] == "STATE_CHANGED"]
    assert sc[-1]["payload"]["reason"] == "JOB_DEAD_LETTERED"
    assert conn.execute("SELECT status, case_id FROM jobs WHERE job_id = %s", (jid,)).fetchone() == {
        "status": "DEAD", "case_id": "ST0-STUCK"}
    conn.commit()
    assert verify_all(conn)["ok"]


def test_dead_letter_without_case_still_audited(conn, tenant):
    jobs.enqueue(conn, tenant_id=tenant, kind="process_dispute", payload=_payload("CN-NONE"))
    j = jobs.claim(conn)
    assert jobs.fail(conn, j, error="bad", retryable=False) == "DEAD"
    ev = conn.execute("SELECT * FROM audit_events WHERE event_type = 'JOB_DEAD_LETTERED'").fetchone()
    assert ev["case_id"] is None and ev["payload"]["control_number"] == "CN-NONE"


def test_reaper_requeues_and_dead_letters_expired_leases(conn, tenant):
    a = jobs.enqueue(conn, tenant_id=tenant, kind="process_dispute", payload={}, max_attempts=3)
    b = jobs.enqueue(conn, tenant_id=tenant, kind="process_dispute", payload={}, max_attempts=1)
    ja, jb = jobs.claim(conn, lease_s=0.001), jobs.claim(conn, lease_s=0.001)
    conn.execute("SELECT pg_sleep(0.01)")
    conn.commit()
    assert jobs.reap_expired_leases(conn) == {"requeued": 1, "dead": 1}
    st = {r["job_id"]: r["status"] for r in conn.execute("SELECT job_id, status FROM jobs").fetchall()}
    assert st == {a: "QUEUED", b: "DEAD"}
    # the stale holder of the old lease can no longer complete or fail it
    assert jobs.complete(conn, ja) is False
    assert jobs.fail(conn, ja, error="late") is None
    again = jobs.claim(conn)
    assert again["job_id"] == a and again["attempts"] == 2 and jobs.complete(conn, again)
    assert jb["job_id"] == b


# ---------------------------------------------------------------- worker
def test_worker_drains_queue_with_pipeline(conn, tenant):
    for i in range(3):
        jobs.enqueue(conn, tenant_id=tenant, kind="process_dispute", payload=_payload(f"CN-{i}"))
    jobs.enqueue(conn, tenant_id=tenant, kind="process_dispute", payload=_payload("CN-0"))   # duplicate
    stats = run_worker(conn, cfg=CFG, deps_for=_fake_deps_for())
    assert stats["done"] == 4 and stats["queue"] == {"DONE": 4}
    assert conn.execute("SELECT count(*) AS n FROM cases").fetchone()["n"] == 3
    linked = conn.execute("SELECT count(*) AS n FROM jobs WHERE case_id IS NOT NULL").fetchone()["n"]
    assert linked == 3                                    # the duplicate's job has no case
    assert verify_all(conn)["ok"]


def test_worker_dead_letters_unprocessable_payload(conn, tenant):
    bad = _payload("CN-BAD")
    bad["envelope"]["fixture_schema_version"] = "unknown-9"
    jobs.enqueue(conn, tenant_id=tenant, kind="process_dispute", payload=bad)
    nonsyn = _payload("CN-NS")
    nonsyn["envelope"]["synthetic"] = False
    jobs.enqueue(conn, tenant_id=tenant, kind="process_dispute", payload=nonsyn)
    stats = run_worker(conn, cfg=CFG, deps_for=_fake_deps_for())
    assert stats["dead"] == 2 and conn.execute("SELECT count(*) AS n FROM cases").fetchone()["n"] == 0


def test_worker_retries_db_failure_and_escalates_stuck_case(conn, tenant, monkeypatch):
    """An exception escaping the pipeline: stuck case escalated, job retried, then dead-lettered."""
    import disputes.workflow.worker as w
    calls = {"n": 0}

    def flaky(c, **kw):
        calls["n"] += 1
        with c.transaction():
            c.execute("INSERT INTO cases (case_id, tenant_id, channel, control_number, state, raw_payload_sha256, "
                      "synthetic) VALUES (%s, %s, 'ACDV', %s, 'RECEIVED', %s, true) ON CONFLICT DO NOTHING",
                      ("ST0-FLAKY", kw["tenant_id"], kw["dispute"].control_number, "0" * 64))
        raise psycopg.OperationalError("simulated connection loss")
    monkeypatch.setattr(w, "process_dispute", flaky)
    jobs.enqueue(conn, tenant_id=tenant, kind="process_dispute", payload=_payload("CN-F"), max_attempts=2)
    stats = run_worker(conn, cfg=CFG, deps_for=_fake_deps_for(), backoff_base_s=0, wait_for_backoff=True,
                       max_wait_s=5)
    assert calls["n"] == 2 and stats["retry"] == 1 and stats["dead"] == 1
    assert repo.get_case(conn, tenant_id=tenant, case_id="ST0-FLAKY")["state"] == "ESCALATED"


# ---------------------------------------------------------------- CLI
def test_cli_ingest_and_work_on_fixture_set(conn, tenant, db_url):
    out = cli.ingest(conn, tenant_id=tenant, fixtures_dir=FIXTURES, fixture_dates=True)
    assert out["enqueued"] == 200
    j = conn.execute("SELECT payload FROM jobs LIMIT 1").fetchone()["payload"]
    assert j["sor_path"].endswith("sor_accounts.jsonl") and j["as_of"].startswith("20")
    stats = run_worker(conn, cfg=CFG, deps_for=_fake_deps_for(), max_jobs=20)
    assert stats["done"] == 20
    assert verify_all(conn)["ok"]


def test_cli_seed_demo(conn):
    out = cli.seed_demo(conn)
    rows = {r["tenant_id"]: r["display_name"] for r in conn.execute("SELECT * FROM tenants").fetchall()}
    assert rows["synthetic-tenant-0"] == "Example Fintech Lender (SYNTHETIC)"
    assert rows["synthetic-tenant-1"] == "Example Auto Finance (SYNTHETIC)"
    if out["skipped_users"]:
        assert conn.execute("SELECT count(*) AS n FROM users").fetchone()["n"] == 0
    else:
        roles = {r["role"] for r in conn.execute("SELECT role FROM users").fetchall()}
        assert roles == {"SPECIALIST", "SUPERVISOR", "ADMIN", "AUDITOR", "CLIENT_VIEWER"}
        viewers = conn.execute("SELECT tenant_id FROM users WHERE role = 'CLIENT_VIEWER' ORDER BY 1").fetchall()
        assert [v["tenant_id"] for v in viewers] == ["synthetic-tenant-0", "synthetic-tenant-1"]
        assert conn.execute("SELECT count(*) AS n FROM staff_tenant_access").fetchone()["n"] == 12
    assert cli.seed_demo(conn)["tenants"]                 # idempotent


def test_cli_seed_demo_with_auth_available(conn, monkeypatch):
    monkeypatch.setattr(cli, "_web_auth", lambda: (lambda p: "hash:" + p, lambda: "TOTPSECRET"))
    out = cli.seed_demo(conn, password="demo-pass")
    assert len(out["users"]) == 8 and out["password"] == "demo-pass"
    assert conn.execute("SELECT count(*) AS n FROM staff_tenant_access").fetchone()["n"] == 12
    assert {r["password_hash"] for r in conn.execute("SELECT password_hash FROM users").fetchall()} == {"hash:demo-pass"}
    assert verify_all(conn)["ok"]


def test_backup_restore_drill_verifies_restored_copy(conn, tenant, db_url, tmp_path):
    """R-32: restore into a NEW database; verify (chains, triggers, anchor) passes there."""
    from disputes.audit.anchor import write_anchor
    for i in range(3):
        run(conn, tenant, Scenario(), make_dispute(f"CN-{i}", account=f"SYNACCT{i:04d}"))
    conn.commit()
    write_anchor(conn, tmp_path / "anchors")
    dump = cli.backup(db_url, tmp_path / "b.dump")
    assert dump["bytes"] > 0
    target = db_url.rsplit("/", 1)[1] + "_restored"
    cli.restore(db_url, dump["file"], target)
    try:
        with connect(db_url.rsplit("/", 1)[0] + "/" + target) as r:
            v = verify_all(r, anchor_dir=str(tmp_path / "anchors"))
            assert v["ok"] and v["trigger_present"] and v["anchor"]["ok"], v
            assert r.execute("SELECT count(*) AS n FROM cases").fetchone()["n"] == 3
            with pytest.raises(psycopg.errors.InsufficientPrivilege):
                r.execute("DELETE FROM audit_events")
        with pytest.raises(SystemExit):                    # never restore over an existing database
            cli.restore(db_url, dump["file"], target)
    finally:
        with psycopg.connect(db_url.rsplit("/", 1)[0] + "/postgres", autocommit=True) as a:
            a.execute(f'DROP DATABASE IF EXISTS "{target}" WITH (FORCE)')


def test_cli_main_verify_and_anchor_subprocess(conn, tenant, db_url, tmp_path):
    run(conn, tenant)
    conn.commit()
    base = [sys.executable, "-m", "disputes.cli", "--database-url", db_url]
    a = subprocess.run(base + ["anchor", "--anchor-dir", str(tmp_path)], cwd=SRC, capture_output=True, text=True)
    assert a.returncode == 0, a.stderr
    v = subprocess.run(base + ["verify", "--anchor-dir", str(tmp_path)], cwd=SRC, capture_output=True, text=True)
    assert v.returncode == 0 and json.loads(v.stdout)["ok"], v.stdout + v.stderr
    m = subprocess.run(base + ["migrate"], cwd=SRC, capture_output=True, text=True)
    assert m.returncode == 0 and json.loads(m.stdout)["applied"] == []
    conn.execute("ALTER TABLE audit_events DISABLE TRIGGER audit_events_insert_only")
    conn.execute("UPDATE audit_events SET payload = '{}'::jsonb WHERE event_id = "
                 "(SELECT min(event_id) FROM audit_events)")
    conn.execute("ALTER TABLE audit_events ENABLE TRIGGER audit_events_insert_only")
    conn.commit()
    bad = subprocess.run(base + ["verify", "--anchor-dir", str(tmp_path)], cwd=SRC, capture_output=True, text=True)
    assert bad.returncode == 1 and json.loads(bad.stdout)["first_broken_event_id"] is not None
