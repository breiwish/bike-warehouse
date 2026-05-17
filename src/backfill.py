"""All-time backfill from Strava. Resumable + rate-limit aware."""
from __future__ import annotations

import json
import time

from . import config as C
from . import ingest, strava, warehouse


def list_all_activities() -> list[dict]:
    """Page through entire athlete history."""
    out = []
    page = 1
    while True:
        chunk = strava.list_activities(page=page, per_page=100)
        if not chunk:
            break
        out.extend(chunk)
        print(f"  fetched page {page}: {len(chunk)} activities (total {len(out)})")
        page += 1
        if len(chunk) < 100:
            break
    return out


def backfill(refresh_existing: bool = False) -> None:
    warehouse.init()
    print("Listing all activities...")
    acts = list_all_activities()
    rides = [a for a in acts if strava.is_ride(a)]
    print(f"Total: {len(acts)}, rides: {len(rides)}")

    # Process newest → oldest so recent data lands first
    rides.sort(key=lambda a: a["start_date"], reverse=True)

    skipped = 0
    done = 0
    failed = []
    for i, a in enumerate(rides, 1):
        aid = a["id"]
        ap = C.ACTIVITIES / f"{aid}.json"
        sp = C.STREAMS / f"{aid}.parquet"
        if ap.exists() and (sp.exists() or a.get("manual")) and not refresh_existing:
            skipped += 1
            continue
        try:
            print(f"[{i}/{len(rides)}] {aid} {a.get('name', '?')[:50]}")
            ingest.add_ride(aid, force=refresh_existing)
            done += 1
        except Exception as e:
            print(f"  FAIL: {e}")
            failed.append((aid, str(e)))
            time.sleep(2)
    warehouse.rebuild_daily_load()
    print(f"\nDone. fetched={done} skipped={skipped} failed={len(failed)}")
    if failed:
        (C.DATA / "backfill_failures.json").write_text(json.dumps(failed, indent=2))


if __name__ == "__main__":
    import sys
    backfill(refresh_existing="--force" in sys.argv)
