#!/usr/bin/env bash
# R-32 restore drill: back up the database, restore it into a NEW database, and run `verify`
# (both chains, insert-only triggers, latest anchor) against the restored copy.
# Usage: scripts/backup_restore_drill.sh [backup_dir]
# Env: DISPUTES_DATABASE_URL (default postgresql://postgres@127.0.0.1:5432/disputes),
#      DISPUTES_ANCHOR_DIR, PYTHON (default: python on PATH), PGBIN (default /usr/lib/postgresql/16/bin).
# The restored database is kept (named in the output) so the drill can be inspected; drop it after.
set -euo pipefail
ROOT=$(cd "$(dirname "$0")/.." && pwd)
PY=${PYTHON:-python}
URL=${DISPUTES_DATABASE_URL:-postgresql://postgres@127.0.0.1:5432/disputes}
OUT_DIR=${1:-/tmp/disputes-backups}
STAMP=$(date -u +%Y%m%dT%H%M%SZ)
FILE="$OUT_DIR/disputes-$STAMP.dump"
TARGET="restore_drill_$(date -u +%Y%m%d%H%M%S)"
cd "$ROOT/src"
echo "== verify source"; "$PY" -m disputes.cli --database-url "$URL" verify >/dev/null && echo "source verify: ok"
echo "== anchor";        "$PY" -m disputes.cli --database-url "$URL" anchor
echo "== backup";        "$PY" -m disputes.cli --database-url "$URL" backup --out "$FILE"
echo "== restore";       "$PY" -m disputes.cli --database-url "$URL" restore --file "$FILE" --target-db "$TARGET"
RESTORED_URL="${URL%/*}/$TARGET"
echo "== verify restored ($TARGET)"
"$PY" -m disputes.cli --database-url "$RESTORED_URL" verify
echo "DRILL PASSED: restored copy $TARGET verifies against the latest anchor"
