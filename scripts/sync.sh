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
  echo "    backed up existing warehouse → data/warehouse.duckdb.bak"
fi

mkdir -p data
gh release download "$TAG" --repo "$REPO" \
  --pattern 'warehouse.duckdb' \
  --pattern 'streams.tar.zst' \
  --pattern 'activities.tar.zst' \
  --output data/{} \
  --clobber 2>&1 | tail -5 || {
    # gh download doesn't support --output {} on all versions; fall back per-file
    for f in warehouse.duckdb streams.tar.zst activities.tar.zst; do
      gh release download "$TAG" --repo "$REPO" --pattern "$f" --output "data/$f" --clobber
    done
  }

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

python3 -c "
import duckdb
con = duckdb.connect('data/warehouse.duckdb', read_only=True)
n = con.execute('SELECT count(*) FROM rides').fetchone()[0]
latest = con.execute('SELECT max(start_date_local) FROM rides').fetchone()[0]
print(f'==> {n} rides, latest ride: {latest}')
"
