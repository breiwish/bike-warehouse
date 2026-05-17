"""Tests for hrTSS, TRIMP, EF, decoupling, zones, gear distribution."""
import math

import numpy as np

from src import metrics


def test_hrtss_1h_at_lthr_equals_100():
    assert abs(metrics.hrtss(avg_hr=170, duration_s=3600,
                              lthr=170, resting_hr=55) - 100.0) < 0.5


def test_hrtss_zero_at_resting():
    assert metrics.hrtss(55, 3600, 170, 55) == 0.0


def test_hrtss_half_duration_quarter_intensity_eighth():
    # 30 min at 85% HRR → ratio 0.85, h = 0.5, score = 0.5 * 0.7225 * 100 = 36.1
    val = metrics.hrtss(0.85 * (170 - 55) + 55, 1800, 170, 55)
    assert abs(val - 36.125) < 1


def test_trimp_zero_for_resting():
    hr = np.full(600, 55.0)
    assert metrics.trimp(hr, max_hr=180, resting_hr=55) == 0.0


def test_trimp_grows_with_intensity():
    base = np.full(600, 120.0)
    hard = np.full(600, 160.0)
    assert metrics.trimp(hard, 180, 55) > metrics.trimp(base, 180, 55) > 0


def test_ef_increases_with_speed():
    hr = np.full(100, 150.0)
    slow = metrics.ef(np.full(100, 4.0), hr)
    fast = metrics.ef(np.full(100, 8.0), hr)
    assert fast > slow


def test_ef_returns_nan_on_empty():
    assert math.isnan(metrics.ef(np.array([]), np.array([])))


def test_decoupling_negative_when_second_half_faster_same_hr():
    """Same HR but faster second half → metric ratio drops → negative pct."""
    hr = np.full(100, 150.0)
    speed = np.concatenate([np.full(50, 5.0), np.full(50, 7.0)])
    # ratio first = 5/150 = 0.033, second = 7/150 = 0.046, change = +40%, but
    # decoupling() uses (num/den) — second half ratio higher → positive
    val = metrics.decoupling(speed, hr)
    assert val > 30  # second half "better" → positive decoupling for speed:HR


def test_decoupling_positive_when_hr_drifts_up_same_speed():
    """HR drift with steady speed = aerobic fatigue → speed:HR ratio drops."""
    speed = np.full(100, 5.0)
    hr = np.concatenate([np.full(50, 140.0), np.full(50, 160.0)])
    val = metrics.decoupling(speed, hr)
    assert val < -10  # second-half ratio worse


def test_hr_zones_distribute_to_correct_zone():
    lthr = 170
    # 100s in Z1 (< 0.81 LTHR = <138)
    hr = np.concatenate([np.full(100, 120.0), np.full(50, 175.0)])
    z = metrics.hr_zones(hr, lthr)
    assert z[0] == 100
    assert z[4] == 50
    assert sum(z) == 150


def test_gear_distribution_returns_ratios_summing_100():
    cad = np.full(100, 85.0)
    speed = np.full(100, 7.5)
    pcts = metrics.gear_distribution(cad, speed)
    assert abs(sum(pcts) - 100.0) < 0.01
