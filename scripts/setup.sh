#!/usr/bin/env bash
# bike-warehouse setup. Idempotent.
set -euo pipefail

cd "$(dirname "$0")/.."

echo "==> bike-warehouse setup"

# 1. Find Python 3.13
if command -v python3.13 >/dev/null 2>&1; then
  PY=python3.13
elif python3 -c 'import sys; sys.exit(0 if sys.version_info >= (3, 13) else 1)' 2>/dev/null; then
  PY=python3
else
  echo "ERROR: Python 3.13+ required. Install via 'brew install python@3.13' or pyenv."
  exit 1
fi

# 2. venv
if [ ! -d .venv ]; then
  echo "==> creating venv"
  "$PY" -m venv .venv
fi
. .venv/bin/activate
pip install --upgrade pip --quiet

# 3. Install deps
if [ "${DEV:-0}" = "1" ]; then
  echo "==> installing dev deps"
  pip install -r requirements-dev.txt --quiet
else
  echo "==> installing runtime deps"
  pip install -r requirements.txt --quiet
fi

# 4. Init warehouse if missing
mkdir -p data/activities data/streams
if [ ! -f data/warehouse.duckdb ]; then
  echo "==> initializing DuckDB warehouse"
  python -m src.warehouse init
fi

# 5. Secrets check
if [ ! -f secrets/strava.json ]; then
  echo
  echo "==> NEXT STEPS"
  echo "1. Create Strava API app at https://www.strava.com/settings/api"
  echo "   - Authorization Callback Domain: localhost"
  echo "2. cp secrets/strava.example.json secrets/strava.json"
  echo "3. Edit secrets/strava.json with your client_id + client_secret"
  echo "4. python -m src.oauth"
  echo "5. python -m src.backfill"
  exit 0
fi

if python -c '
import json, sys
c = json.load(open("secrets/strava.json"))
sys.exit(0 if c.get("refresh_token") else 1)
' 2>/dev/null; then
  echo "==> Strava token present"
else
  echo
  echo "==> NEXT: run OAuth flow"
  echo "    python -m src.oauth"
  exit 0
fi

# 6. If no rides yet, suggest backfill
RIDES=$(python -c 'import duckdb; con=duckdb.connect("data/warehouse.duckdb", read_only=True); print(con.execute("SELECT count(*) FROM rides").fetchone()[0])' 2>/dev/null || echo "0")
if [ "$RIDES" -eq "0" ]; then
  echo
  echo "==> NEXT: backfill all rides (long-running)"
  echo "    nohup python -u -m src.backfill > data/backfill.log 2>&1 &"
  exit 0
fi

echo "==> Ready. $RIDES rides in warehouse."
echo
echo "Try:"
echo "  python -m src.warehouse stats"
echo "  python -m src.dashboard && open site/index.html"
echo "  claude mcp add bike-warehouse --scope user -- \"\$(pwd)/scripts/mcp-launch.sh\""
