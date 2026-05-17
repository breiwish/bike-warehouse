"""Sanity checks on Martin power model."""
import numpy as np

from src import physics


def test_flat_steady_watts_in_range():
    """80 kg rider at 8 m/s on flat asphalt ≈ 120-200 W typical."""
    v = np.full(60, 8.0)
    grade = np.zeros(60)
    w = physics.estimate_watts(v, grade, mass_kg=80, cda=0.32, crr=0.005)
    assert 100 < float(np.mean(w)) < 220, float(np.mean(w))


def test_climb_requires_more_power_than_flat():
    v = np.full(60, 4.0)
    flat = physics.estimate_watts(v, np.zeros(60))
    climb = physics.estimate_watts(v, np.full(60, 6.0))  # 6% grade
    assert float(np.mean(climb)) > float(np.mean(flat)) + 100


def test_zero_speed_zero_watts():
    w = physics.estimate_watts(np.zeros(10), np.zeros(10))
    assert np.allclose(w, 0.0)


def test_descent_clamped_nonneg():
    """Steep descent should clamp at 0 (coasting), not go negative."""
    w = physics.estimate_watts(np.full(30, 10.0), np.full(30, -10.0))
    assert (w >= 0).all()


def test_normalized_power_short_ride_nan():
    assert np.isnan(physics.normalized_power(np.array([100.0, 200.0])))


def test_normalized_power_constant_equals_constant():
    w = np.full(120, 200.0)
    assert abs(physics.normalized_power(w) - 200.0) < 1


def test_vam_zero_on_flat():
    alt = np.full(3600, 100.0)
    assert physics.vam(alt) == 0.0


def test_vam_positive_on_climb():
    # 600 m climb over 1 hour → 600 m/h VAM
    alt = np.linspace(0, 600, 3600)
    assert abs(physics.vam(alt) - 600) < 5


def test_air_density_thinner_at_altitude():
    sea = physics.air_density(15, 0)
    mountain = physics.air_density(15, 3000)
    assert sea > mountain > 0.7
