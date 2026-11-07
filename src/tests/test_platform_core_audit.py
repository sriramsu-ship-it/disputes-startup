"""platform-core: insert-only storage (R-21, R-23), verify (R-21), anchor, CASE_READ (R-21), tamper tests."""
from __future__ import annotations

import json
import os
import stat

import psycopg
import pytest

from disputes.audit.anchor import AnchorExists, latest_anchor, write_anchor
from disputes.audit.chain import GENESIS, canonical, event_body, rfc3339, sha256_hex
from disputes.audit.reads import record_case_read
from disputes.audit.verify import triggers_present, verify_all, verify_case
from disputes.db import repo
from disputes.domain import Role
from test_platform_core_pipeline import Scenario, make_dispute, run


def _populate(conn, tenant, n=3):
    ids = [run(conn, tenant, Scenario(), make_dispute(f"CN-{i}", account=f"SYNACCT{i:04d}"))[0].case_id
           for i in range(n)]
    conn.commit()
    return ids


# ---------------------------------------------------------------- insert-only (R-21, R-23 no delete path)
@pytest.mark.parametrize("table", ["audit_events", "case_artifacts"])
@pytest.mark.parametrize("sql", ["UPDATE {t} SET tenant_id = tenant_id", "DELETE FROM {t}", "TRUNCATE {t} CASCADE"])
def test_insert_only_rejects_update_delete_truncate(conn, tenant, table, sql):
    _populate(conn, tenant, 1)
    with pytest.raises(psycopg.errors.InsufficientPrivilege, match="insert-only"):
        conn.execute(sql.format(t=table))
    conn.rollback()
    assert conn.execute(f"SELECT count(*) AS n FROM {table}").fetchone()["n"] > 0


def test_triggers_present_and_detects_disable(conn, tenant):
    assert triggers_present(conn)
    conn.execute("ALTER TABLE audit_events DISABLE TRIGGER audit_events_insert_only")
    assert not triggers_present(conn)
    v = verify_all(conn)
    assert v["trigger_present"] is False and v["ok"] is False and "trigger" in v["detail"]
    conn.rollback()
    assert triggers_present(conn)


# ---------------------------------------------------------------- verify on a clean log
def test_verify_clean_log(conn, tenant):
    ids = _populate(conn, tenant)
    v = verify_all(conn)
    assert v["ok"] and v["first_broken_event_id"] is None and v["trigger_present"]
    assert v["anchor"] == {"checked": False, "ok": None, "detail": "no anchor directory given"}
    for cid in ids:
        r = verify_case(conn, tenant_id=tenant, case_id=cid)
        assert r["ok"] and r["events"] > 10
    assert verify_case(conn, tenant_id=tenant, case_id="NOPE")["events"] == 0
    assert verify_all.__name__ and set(v) == {"ok", "events", "first_broken_event_id", "trigger_present",
                                              "anchor", "detail"}
    assert set(verify_case(conn, tenant_id=tenant, case_id=ids[0])) == {"ok", "events", "first_broken_event_id",
                                                                         "detail"}


def test_verify_empty_log(conn):
    v = verify_all(conn)
    assert v["ok"] and v["events"] == 0


# ---------------------------------------------------------------- tamper: row edit as superuser
def _tamper(conn, sql, params=()):
    """As the postgres superuser: disable the trigger, change rows, re-enable."""
    conn.execute("ALTER TABLE audit_events DISABLE TRIGGER audit_events_insert_only")
    conn.execute(sql, params)
    conn.execute("ALTER TABLE audit_events ENABLE TRIGGER audit_events_insert_only")
    conn.commit()


def test_payload_edit_reports_first_broken_event(conn, tenant):
    ids = _populate(conn, tenant)
    target = conn.execute("SELECT event_id FROM audit_events WHERE case_id = %s AND event_type = 'RULE_EVALUATED'",
                          (ids[1],)).fetchone()["event_id"]
    _tamper(conn, "UPDATE audit_events SET payload = jsonb_set(payload, '{outcome}', '\"MODIFY\"') "
                  "WHERE event_id = %s", (target,))
    assert triggers_present(conn)
    vc = verify_case(conn, tenant_id=tenant, case_id=ids[1])
    assert not vc["ok"] and vc["first_broken_event_id"] == target and "payload" in vc["detail"]
    assert verify_case(conn, tenant_id=tenant, case_id=ids[0])["ok"]      # other cases unaffected
    va = verify_all(conn)
    assert not va["ok"] and va["first_broken_event_id"] == target


def test_payload_and_hash_edit_breaks_chain(conn, tenant):
    """Attacker also fixes payload_sha256: the case and global hashes no longer match."""
    ids = _populate(conn, tenant, 2)
    row = conn.execute("SELECT * FROM audit_events WHERE case_id = %s ORDER BY event_id LIMIT 1 OFFSET 2",
                       (ids[0],)).fetchone()
    newp = dict(row["payload"], forged=True)
    _tamper(conn, "UPDATE audit_events SET payload = %s::jsonb, payload_sha256 = %s WHERE event_id = %s",
            (canonical(newp), sha256_hex(canonical(newp)), row["event_id"]))
    vc = verify_case(conn, tenant_id=tenant, case_id=ids[0])
    assert vc["first_broken_event_id"] == row["event_id"] and "case_hash" in vc["detail"]
    assert verify_all(conn)["first_broken_event_id"] == row["event_id"]


def test_deleted_row_is_detected_at_next_event(conn, tenant):
    ids = _populate(conn, tenant, 1)
    evs = conn.execute("SELECT event_id FROM audit_events WHERE case_id = %s ORDER BY event_id", (ids[0],)).fetchall()
    victim, nxt = evs[3]["event_id"], evs[4]["event_id"]
    _tamper(conn, "DELETE FROM audit_events WHERE event_id = %s", (victim,))
    assert verify_case(conn, tenant_id=tenant, case_id=ids[0])["first_broken_event_id"] == nxt
    assert verify_all(conn)["first_broken_event_id"] == nxt


# ---------------------------------------------------------------- anchor + full rewrite
def _rewrite_whole_chain(conn, mutate_event_id):
    """A superuser rewrites one payload and recomputes EVERY hash consistently."""
    rows = conn.execute("SELECT * FROM audit_events ORDER BY event_id").fetchall()
    conn.execute("ALTER TABLE audit_events DISABLE TRIGGER audit_events_insert_only")
    gprev, heads = GENESIS, {}
    for r in rows:
        payload = r["payload"]
        if r["event_id"] == mutate_event_id:
            payload = dict(payload, rewritten=True)
        ph = sha256_hex(canonical(payload))
        body = event_body(tenant_id=r["tenant_id"], case_id=r["case_id"], event_type=r["event_type"],
                          actor_type=r["actor_type"], actor_id=r["actor_id"], actor_role=r["actor_role"],
                          occurred_at=rfc3339(r["occurred_at"]), payload_sha256=ph)
        cprev = chash = None
        if r["case_id"] is not None:
            cprev = heads.get((r["tenant_id"], r["case_id"]), GENESIS)
            chash = sha256_hex(cprev + body)
            heads[(r["tenant_id"], r["case_id"])] = chash
        g = sha256_hex(gprev + body)
        conn.execute("UPDATE audit_events SET payload = %s::jsonb, payload_sha256 = %s, case_prev_hash = %s, "
                     "case_hash = %s, global_prev_hash = %s, global_hash = %s WHERE event_id = %s",
                     (canonical(payload), ph, cprev, chash, gprev, g, r["event_id"]))
        gprev = g
    conn.execute("ALTER TABLE audit_events ENABLE TRIGGER audit_events_insert_only")
    conn.commit()


def test_full_rewrite_is_detected_only_by_anchor(conn, tenant, tmp_path):
    _populate(conn, tenant, 2)
    a = write_anchor(conn, tmp_path)
    assert verify_all(conn, anchor_dir=str(tmp_path))["anchor"]["ok"] is True
    first = conn.execute("SELECT min(event_id) AS e FROM audit_events").fetchone()["e"]
    _rewrite_whole_chain(conn, first + 1)
    v = verify_all(conn, anchor_dir=str(tmp_path))
    assert v["first_broken_event_id"] is None           # chains are internally consistent again
    assert v["anchor"]["checked"] and v["anchor"]["ok"] is False and not v["ok"]
    assert str(a["global_head_event_id"]) in v["anchor"]["detail"]


def test_anchor_detects_truncated_tail(conn, tenant, tmp_path):
    _populate(conn, tenant, 1)
    a = write_anchor(conn, tmp_path)
    _tamper(conn, "DELETE FROM audit_events WHERE event_id = %s", (a["global_head_event_id"],))
    v = verify_all(conn, anchor_dir=str(tmp_path))
    assert v["first_broken_event_id"] is None and v["anchor"]["ok"] is False and "missing" in v["anchor"]["detail"]


def test_anchor_is_write_once_and_read_only(conn, tenant, tmp_path):
    _populate(conn, tenant, 1)
    a = write_anchor(conn, tmp_path)
    mode = stat.S_IMODE(os.stat(a["path"]).st_mode)
    assert mode == 0o444
    on_disk = json.loads(open(a["path"]).read())
    assert set(on_disk) == {"global_head_event_id", "global_hash", "at"}
    head = conn.execute("SELECT event_id, global_hash FROM audit_events ORDER BY event_id DESC LIMIT 1").fetchone()
    assert on_disk["global_head_event_id"] == head["event_id"] and on_disk["global_hash"] == head["global_hash"]
    with pytest.raises(AnchorExists):        # same file name -> refused, never overwritten
        import disputes.audit.anchor as anc
        orig = anc.rfc3339
        anc.rfc3339 = lambda ts: a["at"]
        try:
            write_anchor(conn, tmp_path)
        finally:
            anc.rfc3339 = orig
    # a later anchor (more events) becomes the latest
    _populate_more = run(conn, tenant, Scenario(), make_dispute("CN-later", account="SYNACCT9999"))
    conn.commit()
    b = write_anchor(conn, tmp_path)
    assert latest_anchor(tmp_path)["global_head_event_id"] == b["global_head_event_id"] > a["global_head_event_id"]
    assert verify_all(conn, anchor_dir=str(tmp_path))["ok"]


def test_anchor_of_empty_log_and_missing_dir(conn, tmp_path):
    a = write_anchor(conn, tmp_path / "x")
    assert a["global_head_event_id"] == 0 and a["global_hash"] == GENESIS
    assert verify_all(conn, anchor_dir=str(tmp_path / "x"))["anchor"]["ok"] is True
    v = verify_all(conn, anchor_dir=str(tmp_path / "none"))
    assert v["anchor"]["checked"] is False and v["ok"]
    assert latest_anchor(tmp_path / "none") is None


# ---------------------------------------------------------------- CASE_READ (R-21)
def test_record_case_read_for_auditor_and_admin_only(conn, tenant):
    (cid,) = _populate(conn, tenant, 1)
    ev = record_case_read(conn, tenant_id=tenant, case_id=cid, user_id="u-auditor-1", role=Role.AUDITOR)
    assert ev is not None
    record_case_read(conn, tenant_id=tenant, case_id=cid, user_id="u-admin-1", role="ADMIN")
    assert record_case_read(conn, tenant_id=tenant, case_id=cid, user_id="u-spec", role=Role.SPECIALIST) is None
    assert record_case_read(conn, tenant_id=tenant, case_id=cid, user_id="c", role="CLIENT_VIEWER") is None
    reads = [e for e in repo.audit_events_for_case(conn, tenant_id=tenant, case_id=cid)
             if e["event_type"] == "CASE_READ"]
    assert [(e["actor_id"], e["actor_role"], e["actor_type"]) for e in reads] == [
        ("u-auditor-1", "AUDITOR", "HUMAN"), ("u-admin-1", "ADMIN", "HUMAN")]
    assert verify_case(conn, tenant_id=tenant, case_id=cid)["ok"]
    with pytest.raises(repo.NotFound):     # other tenant's case: no event, not found
        record_case_read(conn, tenant_id="synthetic-tenant-1", case_id=cid, user_id="u-auditor-1", role="AUDITOR")
