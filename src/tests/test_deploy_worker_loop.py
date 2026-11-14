"""Deploy module: `work --loop` keeps running, processes jobs that arrive later, survives DB outages,
and stops on signal. Synthetic fixtures only."""
from __future__ import annotations

import os
import signal
import subprocess
import sys
import threading
import time
from pathlib import Path

import psycopg

from disputes.cli import ingest, work_loop
from disputes.config import defaults

SRC = Path(__file__).resolve().parents[1]
FIXTURES = SRC / "data" / "fixtures" / "seed20261019_n200"


def _small_fixture(tmp_path: Path, n: int) -> Path:
    d = tmp_path / "fx"
    d.mkdir()
    lines = (FIXTURES / "acdvs.jsonl").read_text(encoding="utf-8").splitlines()[:n]
    (d / "acdvs.jsonl").write_text("\n".join(lines) + "\n", encoding="utf-8")
    (d / "sor_accounts.jsonl").write_text((FIXTURES / "sor_accounts.jsonl").read_text(encoding="utf-8"),
                                          encoding="utf-8")
    return d


def _counts(url):
    with psycopg.connect(url) as c:
        return dict(c.execute("SELECT status, count(*) FROM jobs GROUP BY status").fetchall())


def test_loop_processes_jobs_enqueued_after_start(db_url, conn, tenant, tmp_path):
    fx = _small_fixture(tmp_path, 3)
    stop = threading.Event()
    t = threading.Thread(target=work_loop, args=(db_url,), kwargs=dict(cfg=defaults(), poll_interval_s=0.2,
                                                                      stop=stop), daemon=True)
    t.start()
    time.sleep(0.6)                       # worker is idle and polling
    assert t.is_alive()
    ingest(conn, tenant_id=tenant, fixtures_dir=fx, fixture_dates=True)
    deadline = time.time() + 60
    while time.time() < deadline:
        c = _counts(db_url)
        if c.get("DONE", 0) + c.get("DEAD", 0) == 3:
            break
        time.sleep(0.2)
    stop.set()
    t.join(timeout=15)
    assert not t.is_alive()
    assert _counts(db_url).get("DONE") == 3


def test_loop_exits_after_idle_polls_for_tests(db_url):
    t0 = time.time()
    assert work_loop(db_url, cfg=defaults(), poll_interval_s=0.05, max_idle_polls=3) == 0
    assert time.time() - t0 < 10


def test_loop_survives_unreachable_database():
    stop = threading.Event()
    t = threading.Thread(target=work_loop, args=("postgresql://nobody@127.0.0.1:1/none",),
                         kwargs=dict(cfg=defaults(), poll_interval_s=0.05, stop=stop, reconnect_max_s=0.2),
                         daemon=True)
    t.start()
    time.sleep(1.0)
    assert t.is_alive()                   # retrying, not crashed
    stop.set()
    t.join(timeout=5)
    assert not t.is_alive()


def test_work_loop_cli_stops_on_sigterm(db_url):
    env = {**os.environ, "PYTHONPATH": str(SRC), "DISPUTES_ENV": "dev"}
    p = subprocess.Popen([sys.executable, "-m", "disputes.cli", "--database-url", db_url, "work", "--loop",
                          "--poll-interval", "0.2"], cwd=SRC, env=env, stdout=subprocess.PIPE,
                         stderr=subprocess.PIPE, text=True)
    try:
        line = p.stdout.readline()
        assert '"worker": "started"' in line
        time.sleep(0.5)
        assert p.poll() is None           # still running on an empty queue
        p.send_signal(signal.SIGTERM)
        out, err = p.communicate(timeout=20)
    finally:
        if p.poll() is None:
            p.kill()
    assert p.returncode == 0, err
    assert '"worker": "stopped"' in out


def test_plain_work_still_exits_when_queue_empty(db_url):
    env = {**os.environ, "PYTHONPATH": str(SRC), "DISPUTES_ENV": "dev"}
    r = subprocess.run([sys.executable, "-m", "disputes.cli", "--database-url", db_url, "work"], cwd=SRC,
                       env=env, capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stderr
