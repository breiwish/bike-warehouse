#!/usr/bin/env bash
# Fast wrapper around sync.sh — skip download when local is already fresh.
#
# Two-stage freshness check:
#   1. If local warehouse mtime > most-recent 07:00 UTC (when daily cron fires),
#      the local copy is already past today's release → skip everything (0 net I/O).
#   2. Otherwise call `gh release view` to compare actual asset timestamps;
#      only download if cloud is genuinely newer.
#
# Flags:
#   --force    bypass all caching, always full sync
#   --quiet    suppress info output
set -euo pipefail

cd "$(dirname "$0")/.."

QUIET=0
FORCE=0
for arg in "$@"; do
  case "$arg" in
    --quiet) QUIET=1 ;;
    --force) FORCE=1 ;;
  esac
done

log() { [ "$QUIET" -eq 0 ] && echo "$@"; }

LOCAL_DB="data/warehouse.duckdb"

if [ "$FORCE" -eq 0 ] && [ -f "$LOCAL_DB" ]; then
  # Compute most-recent 07:00 UTC (today's, or yesterday's if before 07:00 today).
  THRESHOLD=$(python3 -c "
from datetime import datetime, timezone, timedelta
now = datetime.now(timezone.utc)
cutoff = now.replace(hour=7, minute=0, second=0, microsecond=0)
if now < cutoff:
    cutoff -= timedelta(days=1)
print(int(cutoff.timestamp()))
")

  # macOS uses `stat -f %m`, Linux uses `stat -c %Y`. Try both.
  LOCAL_MTIME=$(stat -f %m "$LOCAL_DB" 2>/dev/null || stat -c %Y "$LOCAL_DB" 2>/dev/null)

  if [ -n "${LOCAL_MTIME:-}" ] && [ "$LOCAL_MTIME" -gt "$THRESHOLD" ]; then
    log "==> local already past most-recent 07:00 UTC release. Skip. (0 network)"
    exit 0
  fi

  # Stage 2: ask GH for actual release publish time.
  REPO="${WAREHOUSE_REPO:-breiwish/bike-warehouse}"
  TAG="${WAREHOUSE_TAG:-warehouse-latest}"

  REMOTE_TS=$(gh release view "$TAG" --repo "$REPO" \
                --json assets --jq '[.assets[].updatedAt] | max' 2>/dev/null || echo "")

  if [ -n "$REMOTE_TS" ]; then
    REMOTE_EPOCH=$(python3 -c "
from datetime import datetime
print(int(datetime.fromisoformat('$REMOTE_TS'.replace('Z','+00:00')).timestamp()))
")
    if [ "$LOCAL_MTIME" -ge "$REMOTE_EPOCH" ]; then
      log "==> local newer than release ($(date -r "$LOCAL_MTIME" '+%Y-%m-%d %H:%M') vs release $REMOTE_TS). Skip."
      exit 0
    fi
    log "==> release newer ($REMOTE_TS) than local. Downloading."
  fi
fi

exec ./scripts/sync.sh
