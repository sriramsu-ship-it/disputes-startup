"""Hardening: R-05 periodic clock refresh (idempotent, audited, multi-worker safe) and the shared
effective-config loader used by web, worker and clock refresh. SYNTHETIC data only."""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

import psycopg

from disputes.config import defaults
from disputes.web import configsvc
from disputes.workflow import clock_refresh, effective_config as ec, jobs, worker
from test_web_support import A, case, seeded, sink  # noqa: F401

DUE = date(2026, 12, 15)                     # a Tuesday


def _set(conn, key, value, version=1):
    conn.execute("INSERT INTO config_versions (tenant_id, key, value, version, changed_by, reason) "
                 "VALUES ('ops', %s, %s::jsonb, %s, 'u-admin', 'hardening test change')", (key, value, version))
    conn.commit()


def _at(d: date, hour=15) -> datetime:
    return datetime(d.year, d.month, d.day, hour, tzinfo=timezone.utc)


def _clock_events(conn, case_id):
    return [r["payload"] for r in conn.execute(
        "SELECT payload FROM audit_events WHERE case_id = %s AND event_type = 'CLOCK_STATE_CHANGED' ORDER BY event_id",
        (case_id,)).fetchall()]


def test_refresh_moves_on_track_to_at_risk_to_breached_and_audits_each_change(conn, seeded):
    row = case(conn, "CLK1", "verify", received=DUE - timedelta(days=30), due=DUE)
    v0 = row["version"]
    cfg = defaults()
    r = clock_refresh.refresh_clocks(conn, cfg=cfg, now=_at(date(2026, 11, 20)))
    assert r["ran"] and r["checked"] == 1
    c = conn.execute("SELECT clock_state, internal_target_date, version FROM cases WHERE case_id='CLK1'").fetchone()
    assert c["clock_state"] == "ON_TRACK" and c["internal_target_date"] == date(2026, 12, 10)   # 3 bdays before
    assert _clock_events(conn, "CLK1") == [] and c["version"] == v0             # nothing changed: no write
    clock_refresh.refresh_clocks(conn, cfg=cfg, now=_at(date(2026, 12, 8)))     # 2 bdays before target
    c = conn.execute("SELECT clock_state, state, version FROM cases WHERE case_id='CLK1'").fetchone()
    assert c["clock_state"] == "AT_RISK" and c["state"] == "DRAFT_READY"           # AT_RISK never changes state
    assert c["version"] == v0                                                       # no version bump: no 409
    r = clock_refresh.refresh_clocks(conn, cfg=cfg, now=_at(DUE + timedelta(days=1)))
    assert r["changed"] == 1 and r["newly_breached"] == 1
    evs = _clock_events(conn, "CLK1")
    assert [e["to"] for e in evs] == ["AT_RISK", "BREACHED"]
    last = evs[-1]
    assert last["from"] == "AT_RISK" and last["newly_breached"]
    assert {"holiday_calendar", "time_zone", "rule"} <= set(last["table_versions"])
    assert last["config"]["internal_target_business_days_before_due"] == 3
    # PRD v1.3 §6.1 Q13: a newly BREACHED open case escalates (reason BREACHED, sorts after fraud)
    c = conn.execute("SELECT state, escalation_reasons, priority FROM cases WHERE case_id='CLK1'").fetchone()
    assert c["state"] == "ESCALATED" and "BREACHED" in c["escalation_reasons"]
    assert c["priority"] == clock_refresh.BREACHED_PRIORITY and last["case_state_changed"] is True
    sc = conn.execute("SELECT payload FROM audit_events WHERE case_id='CLK1' AND event_type='STATE_CHANGED' "
                      "ORDER BY event_id DESC LIMIT 1").fetchone()["payload"]
    assert sc["to"] == "ESCALATED" and sc["reason"] == "BREACHED"


def test_refresh_is_idempotent(conn, seeded):
    case(conn, "CLK2", "verify", received=DUE - timedelta(days=30), due=DUE)
    now = _at(DUE + timedelta(days=2))
    first = clock_refresh.refresh_clocks(conn, cfg=defaults(), now=now)
    n = conn.execute("SELECT count(*) AS n FROM audit_events").fetchone()["n"]
    second = clock_refresh.refresh_clocks(conn, cfg=defaults(), now=now)
    assert first["changed"] == 1 and second["changed"] == 0
    assert conn.execute("SELECT count(*) AS n FROM audit_events").fetchone()["n"] == n


def test_closed_cases_are_not_refreshed(conn, seeded):
    case(conn, "CLK3", "submitted", received=DUE - timedelta(days=30), due=DUE)
    case(conn, "CLK4", "out_of_scope", received=DUE - timedelta(days=30), due=DUE)
    r = clock_refresh.refresh_clocks(conn, cfg=defaults(), now=_at(DUE + timedelta(days=5)))
    assert r["checked"] == 0 and r["changed"] == 0


def test_case_locked_by_a_reviewer_is_skipped_then_picked_up(conn, seeded, db_url):
    case(conn, "CLK5", "verify", received=DUE - timedelta(days=30), due=DUE)
    other = psycopg.connect(db_url)
    other.execute("SELECT 1 FROM cases WHERE case_id = 'CLK5' FOR UPDATE")
    r = clock_refresh.refresh_clocks(conn, cfg=defaults(), now=_at(DUE + timedelta(days=1)))
    assert r["skipped_locked"] == 1 and r["changed"] == 0
    other.rollback()
    other.close()
    r = clock_refresh.refresh_clocks(conn, cfg=defaults(), now=_at(DUE + timedelta(days=1)))
    assert r["changed"] == 1


def test_only_one_worker_runs_a_pass_at_a_time(conn, seeded, db_url):
    case(conn, "CLK6", "verify", received=DUE - timedelta(days=30), due=DUE)
    other = psycopg.connect(db_url, autocommit=True)
    other.execute("SELECT pg_advisory_lock(%s)", (clock_refresh._ADVISORY_KEY,))
    r = clock_refresh.refresh_clocks(conn, cfg=defaults(), now=_at(DUE + timedelta(days=1)))
    assert r["ran"] is False and r["changed"] == 0
    other.execute("SELECT pg_advisory_unlock(%s)", (clock_refresh._ADVISORY_KEY,))   # (close() is async)
    other.close()
    assert clock_refresh.refresh_clocks(conn, cfg=defaults(), now=_at(DUE + timedelta(days=1)))["changed"] == 1


def test_one_bad_case_does_not_stop_the_pass(conn, seeded):
    case(conn, "CLK7", "verify", received=DUE - timedelta(days=30), due=DUE)
    case(conn, "CLK8", "verify", received=DUE - timedelta(days=30), due=DUE + timedelta(days=1))
    from disputes.intake.clock import compute_clock

    def flaky(due, now, cfg):
        if due == DUE:
            raise RuntimeError("reference table unreadable")
        return compute_clock(due, now, cfg)
    r = clock_refresh.refresh_clocks(conn, cfg=defaults(), now=_at(DUE + timedelta(days=5)), compute=flaky)
    assert r["errors"] == 1 and r["changed"] == 1


def test_worker_runs_clock_refresh_and_cli_command(conn, seeded, db_url, capsys):
    case(conn, "CLK9", "verify", received=DUE - timedelta(days=30), due=DUE)
    stats = worker.run_worker(conn, cfg=defaults(), deps_for=lambda t, p: None, clock_refresh_s=0,
                              now_fn=lambda: _at(DUE + timedelta(days=1)))
    assert stats["clock_changed"] == 1
    from disputes import cli
    case(conn, "CLK10", "verify", received=DUE - timedelta(days=30), due=DUE)
    assert cli.main(["--database-url", db_url, "refresh-clocks", "--as-of", "2026-12-20T12:00:00+00:00"]) == 0
    assert '"changed": 1' in capsys.readouterr().out


# ------------------------------------------------------------------ shared effective config
def test_web_worker_and_clock_read_the_same_effective_config(conn, seeded):
    _set(conn, "internal_target_business_days_before_due", "5")
    assert ec.effective_config(conn).internal_target_business_days_before_due == 5
    assert configsvc.effective_config(conn) == ec.effective_config(conn)
    case(conn, "CFG1", "verify", received=DUE - timedelta(days=30), due=DUE)
    clock_refresh.refresh_clocks(conn, cfg=ec.effective_config(conn), now=_at(date(2026, 11, 20)))
    row = conn.execute("SELECT internal_target_date FROM cases WHERE case_id = 'CFG1'").fetchone()
    assert row["internal_target_date"] == date(2026, 12, 8)                        # 5 business days before
    assert _clock_events(conn, "CFG1")[-1]["config"]["internal_target_business_days_before_due"] == 5


def test_worker_reloads_config_before_each_job(conn, seeded, monkeypatch):
    seen = []
    monkeypatch.setattr(worker, "process_one", lambda c, job, *, deps_for, cfg, **kw: (seen.append(cfg), "done")[1])
    jobs.enqueue(conn, tenant_id=A, kind=worker.KIND, payload={"x": 1})
    jobs.enqueue(conn, tenant_id=A, kind=worker.KIND, payload={"x": 2})
    loads = iter([3, 7])

    def loader(c):
        return defaults().with_overrides(internal_target_business_days_before_due=next(loads))
    worker.run_worker(conn, cfg=defaults(), deps_for=lambda t, p: None, cfg_loader=loader)
    assert [c.internal_target_business_days_before_due for c in seen] == [3, 7]


def test_bad_stored_config_value_keeps_default(conn, seeded):
    _set(conn, "repeat_window_days", '"ninety"')
    assert ec.effective_config(conn).repeat_window_days == defaults().repeat_window_days


def test_two_admin_approval_still_required(conn, seeded):
    from disputes.web.auth import load_principal
    a1, a2 = load_principal(conn, "u-admin"), load_principal(conn, "u-admin2")
    req = configsvc.propose_change(conn, actor=a1, key="anchor_interval_min", raw_value="20",
                                   reason="hardening test: change anchor interval")
    assert ec.effective_config(conn).anchor_interval_min == 15
    try:
        configsvc.decide_change(conn, actor=a1, request_id=req["request_id"], approve=True)
        raise AssertionError("self-approval must fail")
    except configsvc.ConfigForbidden:
        pass
    configsvc.decide_change(conn, actor=a2, request_id=req["request_id"], approve=True)
    assert ec.effective_config(conn).anchor_interval_min == 20          # the worker's loader sees it


def test_breach_while_in_review_escalates_keeps_work_and_stales_the_form(conn, seeded, sink):
    from disputes.web import actions as act
    from test_web_support import actor
    case(conn, "BR1", "verify", received=DUE - timedelta(days=30), due=DUE)
    spec = actor("u-spec")
    opened = act.open_case(conn, tenant_id=A, case_id="BR1", actor=spec)
    act.edit(conn, tenant_id=A, case_id="BR1", actor=spec, reason_code="NARRATIVE_EDIT_ONLY",
             reason_text="wording before the breach", narrative="We checked the account records.")
    conn.commit()
    form_version = conn.execute("SELECT version FROM cases WHERE case_id='BR1'").fetchone()["version"]
    clock_refresh.refresh_clocks(conn, cfg=defaults(), now=_at(DUE + timedelta(days=1)))
    row = conn.execute("SELECT state, escalation_reasons FROM cases WHERE case_id='BR1'").fetchone()
    assert row["state"] == "ESCALATED" and row["escalation_reasons"] == ["BREACHED"]
    try:
        act.approve(conn, tenant_id=A, case_id="BR1", actor=spec, sink=sink, expected_version=form_version)
        raise AssertionError("a stale form must not approve")
    except act.StaleCase:
        conn.rollback()
    from disputes.web import casedata as cd
    w = cd.working_state(cd.load_bundle(conn, tenant_id=A, case_id="BR1"))
    assert w["narrative"][0]["text"] == "We checked the account records."          # working decision kept
    assert opened is not None


def test_already_escalated_case_gets_breached_reason_without_a_second_transition(conn, seeded):
    case(conn, "BR2", "fraud", received=DUE - timedelta(days=30), due=DUE)
    n0 = conn.execute("SELECT count(*) AS n FROM audit_events WHERE case_id='BR2' AND event_type='STATE_CHANGED'"
                      ).fetchone()["n"]
    clock_refresh.refresh_clocks(conn, cfg=defaults(), now=_at(DUE + timedelta(days=1)))
    row = conn.execute("SELECT state, escalation_reasons, priority FROM cases WHERE case_id='BR2'").fetchone()
    assert row["state"] == "ESCALATED" and "BREACHED" in row["escalation_reasons"]
    assert "ID_FRAUD_SUSPECTED" in row["escalation_reasons"] and row["priority"] == 100   # fraud stays first
    assert conn.execute("SELECT count(*) AS n FROM audit_events WHERE case_id='BR2' AND event_type='STATE_CHANGED'"
                        ).fetchone()["n"] == n0
