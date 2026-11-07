#!/usr/bin/env bash
# Start/stop a throwaway local Postgres 16 for development and tests.
# Usage: scripts/dev_postgres.sh start|stop|status   (port 5432, trust auth on 127.0.0.1 only)
set -euo pipefail
PGBIN=${PGBIN:-$(ls -d /usr/lib/postgresql/*/bin 2>/dev/null | sort -V | tail -1)}
DATA=${PGDATA_DIR:-/tmp/pgdata}
SOCK=${PGSOCK_DIR:-/tmp/pgsock}
PORT=${PGPORT:-5432}
run() { if [ "$(id -u)" = 0 ]; then runuser -u postgres -- "$@"; else "$@"; fi; }
case "${1:-start}" in
  start)
    if run "$PGBIN/pg_ctl" -D "$DATA" status >/dev/null 2>&1; then echo "already running"; exit 0; fi
    mkdir -p "$DATA" "$SOCK"
    [ "$(id -u)" = 0 ] && chown postgres:postgres "$DATA" "$SOCK"
    [ -f "$DATA/PG_VERSION" ] || run "$PGBIN/initdb" -D "$DATA" -A trust -U postgres -E UTF8 --locale=C >/dev/null
    run "$PGBIN/pg_ctl" -D "$DATA" -l "$DATA/log" -w \
      -o "-p $PORT -k $SOCK -c listen_addresses=127.0.0.1 -c max_connections=200" start ;;
  stop) run "$PGBIN/pg_ctl" -D "$DATA" stop ;;
  status) run "$PGBIN/pg_ctl" -D "$DATA" status ;;
esac
