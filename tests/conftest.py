"""Shared fixtures: temp warehouse + synthetic ride."""
from __future__ import annotations

import json

import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq
import pytest


@pytest.fixture
def tmp_repo(tmp_path, monkeypatch):
    """Isolate config to a tmp dir; no real Strava, no real warehouse."""
    monkeypatch.delenv("BIKE_USER", raising=False)
    monkeypatch.setenv("BIKE_SECRETS", str(tmp_path / "secrets"))
    (tmp_path / "secrets").mkdir()
    (tmp_path / "data" / "activities").mkdir(parents=True)
    (tmp_path / "data" / "streams").mkdir(parents=True)

    # Patch config module to point at tmp_path
    from src import config as C
    monkeypatch.setattr(C, "ROOT", tmp_path)
    monkeypatch.setattr(C, "DATA", tmp_path / "data")
    monkeypatch.setattr(C, "ACTIVITIES", tmp_path / "data" / "activities")
    monkeypatch.setattr(C, "STREAMS", tmp_path / "data" / "streams")
    monkeypatch.setattr(C, "DB_PATH", tmp_path / "data" / "warehouse.duckdb")
    monkeypatch.setattr(C, "SECRETS", tmp_path / "secrets")
    return tmp_path


@pytest.fixture
def fake_activity():
    return {
        "id": 42,
        "name": "Test ride",
        "type": "Ride",
        "sport_type": "Ride",
        "start_date": "2025-08-01T15:00:00Z",
        "start_date_local": "2025-08-01T08:00:00",
        "timezone": "America/Los_Angeles",
        "distance": 20000.0,
        "moving_time": 3600,
        "elapsed_time": 3700,
        "total_elevation_gain": 200.0,
        "average_speed": 5.55,
        "max_speed": 12.0,
        "average_heartrate": 145.0,
        "max_heartrate": 170.0,
        "average_cadence": 78.0,
        "average_temp": 22.0,
    }


def _synth_streams(n: int = 3600, base_speed: float = 5.5,
                   base_hr: float = 145, drift: float = 5) -> dict:
    """Build a synthetic 1-hour ride: steady cadence, mild HR drift, flat."""
    rng = np.random.default_rng(0)
    return {
        "t_s": np.arange(n, dtype=np.int32),
        "velocity_ms": (base_speed + rng.normal(0, 0.2, n)).astype(np.float32),
        "heartrate": (base_hr + np.linspace(0, drift, n)
                      + rng.normal(0, 1, n)).astype(np.float32),
        "cadence_rpm": (78 + rng.normal(0, 3, n)).astype(np.float32),
        "altitude_m": (50 + np.cumsum(rng.normal(0, 0.05, n))).astype(np.float32),
        "grade_pct": rng.normal(0, 1, n).astype(np.float32),
        "distance_m": (np.cumsum(np.full(n, base_speed))).astype(np.float32),
        "watts": np.full(n, np.nan, dtype=np.float32),
        "watts_est": (180 + rng.normal(0, 10, n)).astype(np.float32),
        "temp_c": np.full(n, 22.0, dtype=np.float32),
        "moving": np.ones(n, dtype=bool),
        "lat": np.full(n, 37.4, dtype=np.float64),
        "lon": np.full(n, -122.0, dtype=np.float64),
    }


@pytest.fixture
def synth_streams():
    return _synth_streams


@pytest.fixture
def synth_warehouse(tmp_repo, fake_activity, synth_streams):
    """Initialize a warehouse, write a synthetic activity + parquet, upsert row."""
    from src import config as C
    from src import ingest, warehouse
    warehouse.init()

    # Save activity JSON
    (C.ACTIVITIES / f"{fake_activity['id']}.json").write_text(
        json.dumps(fake_activity))

    # Write parquet streams
    s = synth_streams()
    cols = {"activity_id": np.full(len(s["t_s"]), fake_activity["id"],
                                    dtype=np.int64), **s}
    pq.write_table(pa.table(cols),
                   C.STREAMS / f"{fake_activity['id']}.parquet",
                   compression="zstd")

    # Rebuild stream view + upsert
    con = warehouse.connect()
    warehouse._build_stream_view(con)
    con.close()
    row = ingest.compute_row(fake_activity,
                              C.STREAMS / f"{fake_activity['id']}.parquet",
                              lthr=170)
    row = {k: ingest._nan_to_none(v) for k, v in row.items()}
    warehouse.upsert_ride(row)
    warehouse.rebuild_daily_load()
    return tmp_repo
