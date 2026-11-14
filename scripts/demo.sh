#!/usr/bin/env bash
# Local demo wrapper (SYNTHETIC DATA ONLY). Needs Docker Desktop (macOS/Windows via WSL or Git Bash) or
# Docker Engine + compose plugin (Linux). Runbook: docs/engineering/runbook-local-demo.md
#
#   scripts/demo.sh start          build + start everything, wait until ready, print the logins
#   scripts/demo.sh stop           stop containers (data is kept)
#   scripts/demo.sh status         container status + readiness
#   scripts/demo.sh logins         the demo sign-in emails and password
#   scripts/demo.sh logs [svc]     follow logs (svc: web | worker | bootstrap | postgres)
#   scripts/demo.sh test           end-to-end smoke test of the running stack (login + processed cases)
#   scripts/demo.sh reset [--yes]  DELETE all demo data (the database volume) and start fresh
#
# Port: http://localhost:8000 by default. If 8000 is taken:  DISPUTES_PORT=8001 scripts/demo.sh start
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
PORT="${DISPUTES_PORT:-8000}"
export DISPUTES_PORT="$PORT"
DC=(docker compose -f "$ROOT/docker-compose.yml")
FIRST_EMAIL="u-specialist-1@demo.invalid"

die() { echo "ERROR: $*" >&2; exit 1; }

need_docker() {
  command -v docker >/dev/null 2>&1 || die "Docker is not installed. Install Docker Desktop: https://www.docker.com/products/docker-desktop/"
  docker info >/dev/null 2>&1 || die "Docker is installed but not running. Start Docker Desktop and try again."
  docker compose version >/dev/null 2>&1 || die "'docker compose' is missing. Update Docker Desktop (Compose v2 is built in)."
}

port_busy() {  # true if something accepts connections on 127.0.0.1:$1
  (exec 3<>"/dev/tcp/127.0.0.1/$1") >/dev/null 2>&1
}

ours_on_port() {  # true if our web container is the one publishing the port
  [ -n "$("${DC[@]}" ps -q web 2>/dev/null)" ] && "${DC[@]}" port web 8000 2>/dev/null | grep -q ":$PORT\$"
}

wait_ready() {
  local i
  for i in $(seq 1 90); do
    if curl -fsS "http://127.0.0.1:$PORT/readyz" >/dev/null 2>&1; then return 0; fi
    sleep 2
  done
  return 1
}

logins() {
  echo
  echo "Demo is at:  http://localhost:$PORT    (SYNTHETIC data only; local machine only)"
  echo "Password for every demo login: ${DISPUTES_DEMO_PASSWORD:-synthetic-demo-local}"
  echo "MFA: the sign-in page shows the current 6-digit code (local dev mode only)."
  echo "Logins:"
  echo "  u-specialist-1@demo.invalid   analyst (SPECIALIST)  - review and approve cases"
  echo "  u-supervisor-1@demo.invalid   SUPERVISOR            - escalations, second approvals"
  echo "  u-supervisor-2@demo.invalid   SUPERVISOR            - the 'different supervisor' for two-person approval"
  echo "  u-admin-1@demo.invalid        ADMIN                 - configuration"
  echo "  u-auditor-1@demo.invalid      AUDITOR               - read-only audit view"
  echo "  u-client-0@demo.invalid       client portal, Example Fintech Lender (SYNTHETIC)"
  echo "  u-client-1@demo.invalid       client portal, Example Auto Finance (SYNTHETIC)"
  echo "(If you changed DISPUTES_DEMO_PASSWORD after the first start, the old password still applies until 'reset'.)"
}

cmd="${1:-help}"; shift || true
case "$cmd" in
  start)
    need_docker
    if port_busy "$PORT" && ! ours_on_port; then
      die "port $PORT is already in use by another program. Either stop that program, or start the demo on another port:
       DISPUTES_PORT=8001 scripts/demo.sh start      (then open http://localhost:8001)"
    fi
    echo "Building and starting (first run downloads images and can take a few minutes)..."
    "${DC[@]}" up -d --build
    echo "Waiting for the app to become ready..."
    if ! wait_ready; then
      "${DC[@]}" ps
      "${DC[@]}" logs --tail=40 bootstrap web
      die "the app did not become ready in 3 minutes (logs above). Try: scripts/demo.sh logs"
    fi
    logins
    echo "The worker processes the synthetic disputes in the background (about a minute); refresh the queue." ;;
  stop)
    need_docker; "${DC[@]}" stop ;;
  down)
    need_docker; "${DC[@]}" down ;;
  status)
    need_docker; "${DC[@]}" ps
    if curl -fsS "http://127.0.0.1:$PORT/readyz" 2>/dev/null; then echo; else echo "not ready on port $PORT"; fi ;;
  logins)
    logins ;;
  logs)
    need_docker; "${DC[@]}" logs -f --tail=100 "$@" ;;
  test)
    need_docker
    curl -fsS "http://127.0.0.1:$PORT/healthz" >/dev/null || die "nothing healthy on http://127.0.0.1:$PORT (is the demo started?)"
    echo "ok   host port $PORT reachable"
    "${DC[@]}" exec -T web python - --base-url http://127.0.0.1:8000 --email "$FIRST_EMAIL" \
      --password "${DISPUTES_DEMO_PASSWORD:-synthetic-demo-local}" --expect-cases 5 --timeout 180 \
      < "$ROOT/scripts/smoke_test.py" ;;
  reset)
    need_docker
    if [ "${1:-}" != "--yes" ]; then
      read -r -p "This deletes ALL demo data (synthetic) and starts fresh. Type 'reset' to continue: " ans
      [ "$ans" = "reset" ] || die "cancelled"
    fi
    "${DC[@]}" down -v --remove-orphans
    exec "$0" start ;;
  help|-h|--help|*)
    sed -n '2,13p' "$0" | sed 's/^# \{0,1\}//' ;;
esac
