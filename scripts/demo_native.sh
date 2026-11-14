#!/usr/bin/env bash
# Local demo WITHOUT Docker (SYNTHETIC DATA ONLY). macOS / Linux / WSL.
# Needs: Python 3.13 (python3.13 on PATH, or set PYTHON=/path/to/python3.13) and a running
# PostgreSQL 16 you can connect to as a user that may create databases.
#   macOS (Homebrew):  brew install python@3.13 postgresql@16 && brew services start postgresql@16
#   then:              DISPUTES_DATABASE_URL=postgresql://$USER@127.0.0.1:5432/disputes_demo scripts/demo_native.sh start
#
#   scripts/demo_native.sh start    venv + deps (first run), migrate/seed/ingest, start worker + web
#   scripts/demo_native.sh stop     stop worker + web (data stays in the database)
#   scripts/demo_native.sh status | logins | logs | test
#   scripts/demo_native.sh reset    DROP the demo database and start fresh
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PORT="${DISPUTES_PORT:-8000}"
RUN="${DISPUTES_RUN_DIR:-${TMPDIR:-/tmp}/disputes-demo-native}"
VENV="${DISPUTES_VENV:-$ROOT/.venv}"
PY="${PYTHON:-$(command -v python3.13 || true)}"
export DISPUTES_ENV=dev DISPUTES_LLM_BACKEND=offline DISPUTES_DEV_SHOW_TOTP=1 DISPUTES_COOKIE_SECURE=0
export DISPUTES_DATABASE_URL="${DISPUTES_DATABASE_URL:-postgresql://postgres@127.0.0.1:5432/disputes_demo}"
export DISPUTES_DEMO_PASSWORD="${DISPUTES_DEMO_PASSWORD:-synthetic-demo-local}"
export DISPUTES_ANCHOR_DIR="$RUN/anchors"
export PYTHONPATH="$ROOT/src"
mkdir -p "$RUN"

die() { echo "ERROR: $*" >&2; exit 1; }
alive() { [ -f "$RUN/$1.pid" ] && kill -0 "$(cat "$RUN/$1.pid")" 2>/dev/null; }
port_busy() { (exec 3<>"/dev/tcp/127.0.0.1/$1") >/dev/null 2>&1; }

ensure_venv() {
  if [ ! -x "$VENV/bin/python" ]; then
    [ -n "$PY" ] || die "Python 3.13 not found. Install it (macOS: brew install python@3.13) or set PYTHON=/path/to/python3.13"
    "$PY" -c 'import sys; sys.exit(0 if sys.version_info[:2] == (3, 13) else 1)' || die "$PY is not Python 3.13"
    "$PY" -m venv "$VENV"
  fi
  "$VENV/bin/python" -m pip install -q -r "$ROOT/src/requirements.txt"
}

stop_all() {
  for p in web worker; do
    if alive "$p"; then kill "$(cat "$RUN/$p.pid")" 2>/dev/null || true; fi
    rm -f "$RUN/$p.pid"
  done
}

cmd="${1:-help}"; shift || true
case "$cmd" in
  start)
    if alive web || alive worker; then echo "already running (scripts/demo_native.sh stop first)"; exit 0; fi
    port_busy "$PORT" && die "port $PORT is already in use. Use another one: DISPUTES_PORT=8001 scripts/demo_native.sh start"
    ensure_venv
    "$VENV/bin/python" "$ROOT/deploy/bootstrap.py" > "$RUN/bootstrap.log" 2>&1 \
      || { cat "$RUN/bootstrap.log"; die "bootstrap failed (is Postgres running and DISPUTES_DATABASE_URL right?)"; }
    nohup "$VENV/bin/python" -m disputes.cli work --loop --poll-interval 2 > "$RUN/worker.log" 2>&1 &
    echo $! > "$RUN/worker.pid"
    nohup "$VENV/bin/python" -m disputes.cli serve --host 127.0.0.1 --port "$PORT" > "$RUN/web.log" 2>&1 &
    echo $! > "$RUN/web.pid"
    for _ in $(seq 1 60); do curl -fsS "http://127.0.0.1:$PORT/readyz" >/dev/null 2>&1 && break; sleep 1; done
    curl -fsS "http://127.0.0.1:$PORT/readyz" >/dev/null 2>&1 || { tail -20 "$RUN/web.log"; die "web did not become ready"; }
    "$0" logins ;;
  stop) stop_all; echo "stopped" ;;
  status)
    for p in web worker; do alive "$p" && echo "$p: running (pid $(cat "$RUN/$p.pid"))" || echo "$p: stopped"; done
    curl -fsS "http://127.0.0.1:$PORT/readyz" 2>/dev/null && echo || echo "not ready on port $PORT" ;;
  logins)
    echo "Demo is at:  http://localhost:$PORT   (SYNTHETIC data only)"
    echo "Password for every demo login: $DISPUTES_DEMO_PASSWORD   (MFA code is shown on the sign-in page)"
    echo "Logins: u-specialist-1@demo.invalid, u-supervisor-1@demo.invalid, u-supervisor-2@demo.invalid,"
    echo "        u-admin-1@demo.invalid, u-auditor-1@demo.invalid, u-client-0@demo.invalid, u-client-1@demo.invalid" ;;
  logs) tail -n 100 -f "$RUN/web.log" "$RUN/worker.log" ;;
  test)
    "$VENV/bin/python" "$ROOT/scripts/smoke_test.py" --base-url "http://127.0.0.1:$PORT" \
      --email u-specialist-1@demo.invalid --password "$DISPUTES_DEMO_PASSWORD" --expect-cases 5 --timeout 180 ;;
  reset)
    stop_all
    "$VENV/bin/python" - <<'EOF'
import os, psycopg
from urllib.parse import urlsplit, urlunsplit
u = urlsplit(os.environ["DISPUTES_DATABASE_URL"]); name = u.path.lstrip("/")
assert name.startswith("disputes_demo"), "refusing to drop a database not named disputes_demo*"
with psycopg.connect(urlunsplit((u.scheme, u.netloc, "/postgres", u.query, "")), autocommit=True) as c:
    c.execute(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)')
print(f"dropped {name}")
EOF
    exec "$0" start ;;
  *) sed -n '2,14p' "$0" | sed 's/^# \{0,1\}//' ;;
esac
