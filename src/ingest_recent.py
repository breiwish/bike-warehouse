"""Incremental ingest: pull recent Strava activities, add only new ones.

Usage:
    python -m src.ingest_recent              # last 7 days
    python -m src.ingest_recent --days 30    # custom window
    python -m src.ingest_recent --all        # full backfill (same as backfill)
"""
from __future__ import annotations

import argparse
import time

from . import ingest, strava, warehouse


def run(days: int = 7) -> dict:
    warehouse.init()
    after = int(time.time() - days * 86400)
    acts = strava.list_activities(after_epoch=after, per_page=100)
    rides = [a for a in acts if strava.is_ride(a)]
    print(f"Strava returned {len(acts)} activities, {len(rides)} rides "
          f"in last {days}d.")

    con = warehouse.connect(readonly=True)
    existing = {r[0] for r in con.execute("SELECT activity_id FROM rides").fetchall()}
    con.close()

    new_rides = [r for r in rides if r["id"] not in existing]
    print(f"{len(new_rides)} new rides to ingest "
          f"(skipping {len(rides) - len(new_rides)} already present).")

    ingested = []
    failed = []
    for r in new_rides:
        try:
            ingest.add_ride(r["id"])
            ingested.append(r["id"])
        except Exception as e:
            print(f"  FAIL {r['id']}: {e}")
            failed.append((r["id"], str(e)))

    if ingested:
        warehouse.rebuild_daily_load()
        print("daily_load rebuilt")

    return {"checked": len(rides), "new": len(new_rides),
            "ingested": len(ingested), "failed": len(failed)}


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=7)
    ap.add_argument("--all", action="store_true")
    args = ap.parse_args()

    if args.all:
        from . import backfill
        backfill.backfill()
    else:
        out = run(days=args.days)
        print(out)
