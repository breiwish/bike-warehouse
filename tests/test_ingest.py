"""Ingest: compute_row from synthetic activity + streams."""
import numpy as np
import pyarrow.parquet as pq

from src import ingest


def test_compute_row_basic_fields(tmp_repo, fake_activity):
    row = ingest.compute_row(fake_activity, streams_path=None, lthr=170)
    assert row["activity_id"] == 42
    assert row["distance_km"] == 20.0
    assert row["avg_hr"] == 145.0
    assert row["has_streams"] is False
    # without streams, derived metrics are None except hrtss
    assert row["trimp"] is None
    assert row["ef"] is None
    assert row["hrtss"] > 0  # has avg_hr + duration


def test_compute_row_with_streams(tmp_repo, fake_activity, synth_streams):
    """Synthetic 1h ride at 145bpm avg ≈ hrTSS ~50, EF positive, mild +decoup."""
    import pyarrow as pa

    from src import config as C

    s = synth_streams()
    cols = {"activity_id": np.full(len(s["t_s"]), 42, dtype=np.int64), **s}
    parquet = C.STREAMS / "42.parquet"
    pq.write_table(pa.table(cols), parquet, compression="zstd")

    row = ingest.compute_row(fake_activity, parquet, lthr=170)
    row = {k: ingest._nan_to_none(v) for k, v in row.items()}
    assert row["has_streams"] is True
    assert row["trimp"] is not None and row["trimp"] > 0
    assert row["ef"] is not None and row["ef"] > 0
    assert row["np_est_w"] is not None
    assert row["vam_mph"] >= 0
    assert isinstance(row["gear_pct"], list) and len(row["gear_pct"]) == 10
    assert abs(sum(row["gear_pct"]) - 100.0) < 0.5


def test_nan_to_none_helper():
    assert ingest._nan_to_none(float("nan")) is None
    assert ingest._nan_to_none(float("inf")) is None
    assert ingest._nan_to_none(None) is None
    assert ingest._nan_to_none(1.5) == 1.5
    assert ingest._nan_to_none(0) == 0
    assert ingest._nan_to_none("x") == "x"
