"""Ride-level metrics: hrTSS, TRIMP, EF, decoupling, zones."""
from __future__ import annotations

import math

import numpy as np

from . import config as C


def hrtss(avg_hr: float, duration_s: float, lthr: float,
          resting_hr: float = None) -> float:
    """HR-based TSS. 100 = 1 hour at LTHR."""
    rh = resting_hr if resting_hr is not None else C.RESTING_HR
    if lthr <= rh:
        return 0.0
    ratio = (avg_hr - rh) / (lthr - rh)
    h = duration_s / 3600.0
    return float(h * ratio ** 2 * 100.0)


def trimp(hr_series: np.ndarray, max_hr: float, resting_hr: float = None,
          dt_s: float = 1.0, male: bool = True) -> float:
    """Banister TRIMP (sex-weighted)."""
    rh = resting_hr if resting_hr is not None else C.RESTING_HR
    if max_hr <= rh:
        return 0.0
    hr = np.asarray(hr_series, dtype=float)
    hr = hr[np.isfinite(hr)]
    if len(hr) == 0:
        return 0.0
    hr_res = (hr - rh) / (max_hr - rh)
    hr_res = np.clip(hr_res, 0.0, 1.0)
    k = 1.92 if male else 1.67
    weight = 0.64 * np.exp(k * hr_res)
    return float(np.sum(hr_res * weight * dt_s / 60.0))


def ef(speed_ms: np.ndarray, hr: np.ndarray) -> float:
    """Efficiency Factor = speed/HR. Pace-based proxy for aerobic fitness."""
    s = np.asarray(speed_ms, dtype=float)
    h = np.asarray(hr, dtype=float)
    mask = np.isfinite(s) & np.isfinite(h) & (h > 0)
    if mask.sum() == 0:
        return float("nan")
    return float(np.mean(s[mask]) / np.mean(h[mask]) * 100.0)


def decoupling(metric_num: np.ndarray, metric_den: np.ndarray) -> float:
    """Pa:HR or Pw:HR decoupling. Pct change from first half to second.
    Negative = second half worse (drifting HR for same pace)."""
    n = np.asarray(metric_num, dtype=float)
    d = np.asarray(metric_den, dtype=float)
    mid = len(n) // 2
    a = np.nanmean(n[:mid]) / np.nanmean(d[:mid])
    b = np.nanmean(n[mid:]) / np.nanmean(d[mid:])
    if not math.isfinite(a) or a == 0:
        return float("nan")
    return float((b - a) / a * 100.0)


def hr_zones(hr: np.ndarray, lthr: float, dt_s: float = 1.0) -> list[int]:
    """Coggan-ish 5 zones based on LTHR. Returns seconds in [Z1..Z5]."""
    bounds = [0.0, 0.81, 0.89, 0.94, 1.0, 99.0]  # multiples of LTHR
    h = np.asarray(hr, dtype=float)
    h = h[np.isfinite(h)]
    if len(h) == 0:
        return [0, 0, 0, 0, 0]
    ratio = h / lthr
    secs = []
    for lo, hi in zip(bounds[:-1], bounds[1:]):
        secs.append(int(((ratio >= lo) & (ratio < hi)).sum() * dt_s))
    return secs


def gear_distribution(cadence: np.ndarray, speed_ms: np.ndarray) -> list[float]:
    """% time in each gear based on closest gear ratio."""
    c = np.asarray(cadence, dtype=float)
    v = np.asarray(speed_ms, dtype=float)
    mask = np.isfinite(c) & np.isfinite(v) & (c > 30) & (v > 1.0)
    if mask.sum() == 0:
        return [0.0] * len(C.RATIOS)
    wheel_rps = v[mask] / C.TIRE_CIRC_M
    pedal_rps = c[mask] / 60.0
    used = wheel_rps / np.where(pedal_rps > 0, pedal_rps, 1)
    counts = np.zeros(len(C.RATIOS))
    for ratio in used:
        idx = int(np.argmin(np.abs(np.array(C.RATIOS) - ratio)))
        counts[idx] += 1
    return (counts / counts.sum() * 100.0).tolist()
