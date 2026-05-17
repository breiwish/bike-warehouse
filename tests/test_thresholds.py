"""Threshold detection from synthetic streams."""

from src import config as C
from src import thresholds, warehouse


def test_detect_lthr_finds_sustained_hr(synth_warehouse):
    con = warehouse.connect()
    lthr, rh = thresholds.detect_lthr(con)
    con.close()
    # synthetic ride avg HR ≈ 147 (145 base + 5 drift mid) → best 20min ≈ 150
    # minus 4 fudge → ~145
    assert 130 < lthr < 165
    # Synthetic min HR ≈ 143, > 70 → falls back to default 55
    assert rh == C.RESTING_HR


def test_detect_lthr_no_streams_returns_default(tmp_repo):
    warehouse.init()
    con = warehouse.connect()
    lthr, rh = thresholds.detect_lthr(con)
    con.close()
    # Empty stub view → no data → defaults
    assert lthr == C.DEFAULT_LTHR
    assert rh == C.RESTING_HR


def test_detect_full_pipeline_inserts_threshold_row(synth_warehouse):
    out = thresholds.detect(refit_metrics=False)
    assert out["lthr"] > 0
    con = warehouse.connect(readonly=True)
    n = con.execute("SELECT count(*) FROM thresholds").fetchone()[0]
    con.close()
    assert n == 1
