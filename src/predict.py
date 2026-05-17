"""Pre-ride prediction: GPX or profile → predicted time, HR, hrTSS, pacing.

Method:
  1. Required watts per segment from physics at target speed.
  2. Personal HR-power curve from history maps watts_est → HR.
  3. Pick speeds that hold HR ≤ pacing_target (default LTHR * 0.92 = endurance).
  4. Apply durability decay past CTL-derived threshold (drift up HR over time).
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import gpxpy
import numpy as np

from . import config as C
from . import metrics, physics, warehouse


@dataclass
class Segment:
    distance_m: float
    grade_pct: float
    elev_gain_m: float


def parse_gpx(path: Path | str, resample_m: float = 50.0) -> list[Segment]:
    """Read GPX, resample to ~uniform distance bins, compute grade per bin."""
    gpx = gpxpy.parse(open(path).read())
    pts = [p for trk in gpx.tracks for seg in trk.segments for p in seg.points]
    if len(pts) < 2:
        return []
    # cumulative distance
    cum = [0.0]
    for a, b in zip(pts[:-1], pts[1:]):
        cum.append(cum[-1] + a.distance_3d(b))
    total = cum[-1]
    n_bins = max(int(total / resample_m), 1)
    bins = np.linspace(0, total, n_bins + 1)
    elev_at = np.interp(bins, cum, [p.elevation or 0 for p in pts])
    segs = []
    for i in range(n_bins):
        d = bins[i + 1] - bins[i]
        de = elev_at[i + 1] - elev_at[i]
        grade = (de / d * 100.0) if d > 0 else 0.0
        segs.append(Segment(distance_m=d, grade_pct=grade,
                            elev_gain_m=max(de, 0)))
    return segs


def fit_hr_power_curve(con) -> tuple[float, float]:
    """Linear: HR ≈ a + b * watts_est, fit from moving samples.
    Returns (a, b)."""
    row = con.execute("""
        SELECT regr_intercept(heartrate, watts_est),
               regr_slope(heartrate, watts_est)
        FROM streams
        WHERE moving AND heartrate IS NOT NULL AND watts_est > 30
    """).fetchone()
    return (float(row[0]) if row[0] else 80.0,
            float(row[1]) if row[1] else 0.25)


def predict_speed_for_hr_cap(segment: Segment, target_hr: float,
                              a: float, b: float,
                              mass_kg: float = None,
                              cda: float = None, crr: float = None) -> float:
    """Solve for speed s.t. estimated HR == target."""
    target_w = max((target_hr - a) / b, 30.0)
    # Find v s.t. watts(v, grade) == target_w (monotonic in v for grade ≥ 0)
    m = (mass_kg or C.RIDER_KG + C.BIKE_KG)
    cda = cda or C.CDA
    crr = crr or C.CRR

    def watts_at_v(v):
        return physics.estimate_watts(
            np.array([v]), np.array([segment.grade_pct]),
            altitude_m=None, mass_kg=m, cda=cda, crr=crr
        )[0]

    lo, hi = 0.5, 25.0  # m/s
    for _ in range(60):
        mid = (lo + hi) / 2
        if watts_at_v(mid) < target_w:
            lo = mid
        else:
            hi = mid
    return (lo + hi) / 2


def predict(gpx_path: str, pacing: str = "endurance") -> dict:
    """Pacing: 'endurance' (LTHR*0.85), 'tempo' (LTHR*0.92), 'threshold' (LTHR)."""
    segs = parse_gpx(gpx_path)
    if not segs:
        return {"error": "no GPX points"}

    con = warehouse.connect(readonly=True)
    lthr = warehouse.latest_lthr(con)
    a, b = fit_hr_power_curve(con)
    con.close()

    pace_map = {"endurance": 0.85, "tempo": 0.92, "threshold": 1.0}
    target_hr = lthr * pace_map.get(pacing, 0.85)

    total_dist = 0.0
    total_time = 0.0
    total_climb = 0.0
    hr_samples = []
    watt_samples = []
    pacing_per_seg = []

    for s in segs:
        v = predict_speed_for_hr_cap(s, target_hr, a, b)
        v = max(v, 0.5)
        t = s.distance_m / v
        w = physics.estimate_watts(np.array([v]), np.array([s.grade_pct]))[0]
        # durability: HR drifts +2% per hour past 1h
        elapsed_h = total_time / 3600.0
        drift = 1.0 + max(0, (elapsed_h - 1.0)) * 0.02
        hr_est = (a + b * w) * drift
        hr_samples.append((t, hr_est))
        watt_samples.append((t, w))
        pacing_per_seg.append({"grade": round(s.grade_pct, 1),
                                "v_kmh": round(v * 3.6, 1),
                                "w_est": round(float(w))})
        total_dist += s.distance_m
        total_time += t
        total_climb += s.elev_gain_m

    avg_hr = sum(t * h for t, h in hr_samples) / sum(t for t, _ in hr_samples)
    np_est = physics.normalized_power(
        np.repeat([w for _, w in watt_samples],
                  [int(t) for t, _ in watt_samples] or [1]))
    hrtss_est = metrics.hrtss(avg_hr, total_time, lthr)

    return {
        "pacing": pacing,
        "distance_km": round(total_dist / 1000, 2),
        "elev_gain_m": round(total_climb),
        "predicted_time_s": int(total_time),
        "predicted_time_hms": f"{int(total_time//3600)}:{int(total_time%3600//60):02d}:{int(total_time%60):02d}",
        "predicted_avg_hr": round(avg_hr, 1),
        "predicted_avg_speed_kmh": round(total_dist / total_time * 3.6, 1),
        "predicted_np_w": round(float(np_est)),
        "predicted_hrtss": round(hrtss_est, 1),
        "lthr_used": lthr,
        "segments_preview": pacing_per_seg[:10],
    }


if __name__ == "__main__":
    import json
    import sys
    if len(sys.argv) < 2:
        print("usage: python -m src.predict <gpx_path> [pacing]")
        sys.exit(1)
    print(json.dumps(predict(sys.argv[1],
                              sys.argv[2] if len(sys.argv) > 2 else "endurance"),
                     indent=2))
