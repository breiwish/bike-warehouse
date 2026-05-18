#!/usr/bin/env bash
# Pull the latest warehouse snapshot from the GH Actions release.
# Replaces local data/warehouse.duckdb + data/streams/ + data/activities/.
set -euo pipefail

cd "$(dirname "$0")/.."

REPO="${WAREHOUSE_REPO:-breiwish/bike-warehouse}"
TAG="${WAREHOUSE_TAG:-warehouse-latest}"

echo "==> syncing from $REPO release '$TAG'"

if [ -f data/warehouse.duckdb ]; then
  cp data/warehouse.duckdb data/warehouse.duckdb.bak
  echo "    backed up existing → data/warehouse.duckdb.bak"
fi

mkdir -p data
for asset in warehouse.duckdb streams.tar.zst activities.tar.zst; do
  echo "    fetching $asset"
  gh release download "$TAG" --repo "$REPO" \
    --pattern "$asset" --output "data/$asset" --clobber
done

if [ -f data/streams.tar.zst ]; then
  rm -rf data/streams
  tar --use-compress-program=unzstd -xf data/streams.tar.zst -C data/
  rm data/streams.tar.zst
fi
if [ -f data/activities.tar.zst ]; then
  rm -rf data/activities
  tar --use-compress-program=unzstd -xf data/activities.tar.zst -C data/
  rm data/activities.tar.zst
fi

# Use repo venv if present, else system python
PY=python3
if [ -x .venv/bin/python ]; then PY=.venv/bin/python; fi

"$PY" -c "
import duckdb
con = duckdb.connect('data/warehouse.duckdb', read_only=True)
n = con.execute('SELECT count(*) FROM rides').fetchone()[0]
latest = con.execute('SELECT max(start_date_local) FROM rides').fetchone()[0]
print(f'==> {n} rides, latest: {latest}')
"
