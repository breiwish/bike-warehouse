"""Single-ride ingestion: raw json + streams parquet + DB row."""
from __future__ import annotations

import json
import math
from pathlib import Path

import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq

from . import config as C
from . import metrics, physics, strava, warehouse


def _activity_path(aid: int) -> Path:
    return C.ACTIVITIES / f"{aid}.json"


def _stream_path(aid: int) -> Path:
    return C.STREAMS / f"{aid}.parquet"


def fetch_and_save(activity_id: int, force: bool = False) -> tuple[Path, Path | None]:
    """Fetch activity + streams from Strava, save to disk."""
    C.ACTIVITIES.mkdir(parents=True, exist_ok=True)
    C.STREAMS.mkdir(parents=True, exist_ok=True)
    ap = _activity_path(activity_id)
    sp = _stream_path(activity_id)

    if not ap.exists() or force:
        act = strava.get_activity(activity_id)
        ap.write_text(json.dumps(act, indent=2))
    else:
        act = json.loads(ap.read_text())

    has_streams = False
    if act.get("manual"):
        sp = None
    elif not sp.exists() or force:
        try:
            streams = strava.get_streams(activity_id)
            tbl = _streams_to_table(activity_id, streams)
            if tbl is not None:
                pq.write_table(tbl, sp, compression="zstd")
                has_streams = True
        except Exception as e:
            print(f"  stream fetch failed: {e}")
            sp = None
    else:
        has_streams = True

    return ap, sp if has_streams or (sp and sp.exists()) else None


def _streams_to_table(activity_id: int, streams: dict) -> pa.Table | None:
    """Strava streams keyed by type → flat columnar."""
    if not streams or "time" not in streams:
        return None
    n = len(streams["time"]["data"])
    cols = {"activity_id": np.full(n, activity_id, dtype=np.int64),
            "t_s": np.asarray(streams["time"]["data"], dtype=np.int32)}

    def col(key, dtype=np.float32, default=np.nan):
        d = streams.get(key, {}).get("data")
        if d is None:
            return np.full(n, default, dtype=dtype)
        arr = np.asarray(d, dtype=object)
        return arr if dtype is object else np.asarray(d, dtype=dtype)

    cols["altitude_m"] = col("altitude")
    cols["velocity_ms"] = col("velocity_smooth")
    cols["cadence_rpm"] = col("cadence")
    cols["heartrate"] = col("heartrate")
    cols["watts"] = col("watts")
    cols["grade_pct"] = col("grade_smooth")
    cols["distance_m"] = col("distance")
    cols["temp_c"] = col("temp")
    cols["moving"] = np.asarray(streams.get("moving", {}).get("data", [True] * n), dtype=bool)

    # latlng split
    ll = streams.get("latlng", {}).get("data")
    if ll:
        ll = np.asarray(ll, dtype=np.float64)
        cols["lat"] = ll[:, 0]
        cols["lon"] = ll[:, 1]
    else:
        cols["lat"] = np.full(n, np.nan, dtype=np.float64)
        cols["lon"] = np.full(n, np.nan, dtype=np.float64)

    # estimated watts via physics
    cols["watts_est"] = physics.estimate_watts(
        cols["velocity_ms"], cols["grade_pct"], cols["altitude_m"]
    ).astype(np.float32)

    return pa.table(cols)


def _nan_to_none(v):
    """DB-safe coerce: NaN/inf → None, otherwise pass through."""
    if v is None:
        return None
    if isinstance(v, float) and (math.isnan(v) or math.isinf(v)):
        return None
    return v


def compute_row(activity: dict, streams_path: Path | None, lthr: int) -> dict:
    """Build the row to insert into rides table."""
    s = streams_path
    gear = activity.get("gear") or {}
    row = {
        "activity_id": activity["id"],
        "name": activity.get("name"),
        "start_date_utc": activity.get("start_date"),
        "start_date_local": activity.get("start_date_local"),
        "timezone": activity.get("timezone"),
        "type": activity.get("type"),
        "sport_type": activity.get("sport_type"),
        "distance_km": (activity.get("distance") or 0) / 1000.0,
        "moving_s": activity.get("moving_time"),
        "elapsed_s": activity.get("elapsed_time"),
        "elev_gain_m": activity.get("total_elevation_gain"),
        "avg_speed_kmh": (activity.get("average_speed") or 0) * 3.6,
        "max_speed_kmh": (activity.get("max_speed") or 0) * 3.6,
        "avg_hr": activity.get("average_heartrate"),
        "max_hr": activity.get("max_heartrate"),
        "avg_cad": activity.get("average_cadence"),
        "calories": activity.get("calories"),
        "avg_temp_c": activity.get("average_temp"),
        "gear_id": activity.get("gear_id"),
        "gear_name": gear.get("name"),
        "trainer": bool(activity.get("trainer")),
        "commute": bool(activity.get("commute")),
        "has_streams": bool(s),
        "raw_path": str(_activity_path(activity["id"])),
    }

    # computed
    avg_hr = row["avg_hr"] or 0
    dur = row["moving_s"] or 0
    row["hrtss"] = metrics.hrtss(avg_hr, dur, lthr) if avg_hr else None

    if s and s.exists():
        import warnings

        import pyarrow.parquet as pq
        t = pq.read_table(s).to_pydict()
        hr = np.asarray(t["heartrate"], dtype=float)
        v = np.asarray(t["velocity_ms"], dtype=float)
        cad = np.asarray(t["cadence_rpm"], dtype=float)
        alt = np.asarray(t["altitude_m"], dtype=float)
        w_est = np.asarray(t["watts_est"], dtype=float)

        def _safe_nanmax(a):
            with warnings.catch_warnings():
                warnings.simplefilter("ignore", RuntimeWarning)
                return float(np.nanmax(a)) if np.isfinite(a).any() else None

        def _safe_nanmean(a):
            with warnings.catch_warnings():
                warnings.simplefilter("ignore", RuntimeWarning)
                return float(np.nanmean(a)) if np.isfinite(a).any() else None

        has_hr = np.isfinite(hr).any()
        max_hr = row["max_hr"] or (_safe_nanmax(hr) if has_hr else None)

        with warnings.catch_warnings():
            warnings.simplefilter("ignore", RuntimeWarning)
            row["trimp"] = metrics.trimp(hr, max_hr or 190) if has_hr else None
            row["ef"] = metrics.ef(v, hr) if has_hr else None
            row["decoupling_pct"] = metrics.decoupling(v, hr) if has_hr else None
        row["np_est_w"] = physics.normalized_power(w_est)
        row["avg_watts_est"] = _safe_nanmean(w_est)
        row["vam_mph"] = physics.vam(alt)
        if has_hr:
            zones = metrics.hr_zones(hr, lthr)
            row.update({f"z{i+1}_s": zones[i] for i in range(5)})
        else:
            for i in range(5):
                row[f"z{i+1}_s"] = None
        row["gear_pct"] = metrics.gear_distribution(cad, v)
    else:
        for k in ["trimp", "ef", "decoupling_pct", "np_est_w", "avg_watts_est", "vam_mph"]:
            row[k] = None
        for i in range(5):
            row[f"z{i+1}_s"] = None
        row["gear_pct"] = None

    return row


def add_ride(activity_id: int, force: bool = False) -> None:
    """Public entry point: fetch + compute + upsert."""
    ap, sp = fetch_and_save(activity_id, force=force)
    activity = json.loads(ap.read_text())
    lthr = warehouse.latest_lthr()
    row = compute_row(activity, sp, lthr)
    row = {k: _nan_to_none(v) for k, v in row.items()}
    warehouse.upsert_ride(row)
    print(f"  ✓ {activity_id} {activity.get('name', '?')} → warehouse")


if __name__ == "__main__":
    import sys
    warehouse.init()
    for aid in sys.argv[1:]:
        add_ride(int(aid))
