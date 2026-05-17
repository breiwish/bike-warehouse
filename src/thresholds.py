"""Auto-detect LTHR, resting HR, FTP-estimate, CdA/Crr fit."""
from __future__ import annotations

import duckdb

from . import config as C
from . import warehouse


def detect_lthr(con: duckdb.DuckDBPyConnection) -> tuple[int, int]:
    """LTHR = avg HR of best 20-min sustained effort across history.
    Resting HR = 1st percentile across all stream samples (moving=true)."""
    row = con.execute("""
        WITH clean AS (
            SELECT activity_id, t_s, heartrate
            FROM streams
            WHERE heartrate IS NOT NULL
              AND isfinite(heartrate)
              AND heartrate > 30
              AND moving
        ), win AS (
            SELECT activity_id, t_s,
                   avg(heartrate) OVER (
                       PARTITION BY activity_id
                       ORDER BY t_s
                       ROWS BETWEEN 599 PRECEDING AND 600 FOLLOWING
                   ) AS hr_20min
            FROM clean
        )
        SELECT max(hr_20min) FROM win
        WHERE hr_20min IS NOT NULL AND isfinite(hr_20min)
    """).fetchone()
    lthr_raw = row[0] if row else None
    if lthr_raw and lthr_raw == lthr_raw:
        # Max 20-min HR ≈ LTHR + 3-5; subtract ~4 to approximate threshold
        lthr = max(int(round(lthr_raw)) - 4, 140)
    else:
        lthr = C.DEFAULT_LTHR

    rh_row = con.execute("""
        SELECT quantile_cont(heartrate, 0.01) FROM streams
        WHERE heartrate > 30 AND isfinite(heartrate) AND moving
    """).fetchone()
    rh_detected = (int(round(rh_row[0]))
                   if rh_row and rh_row[0] and rh_row[0] == rh_row[0]
                   else None)
    # Detected from moving samples = lowest active HR, not true resting.
    # Only trust if it lands in a plausible resting range (35-70).
    rh = rh_detected if (rh_detected and rh_detected <= 70) else C.RESTING_HR
    return lthr, rh


def detect_ftp_est(con: duckdb.DuckDBPyConnection, lthr: int) -> float:
    """FTP-estimate = avg est watts during best 20-min effort whose HR ≈ LTHR.
    Falls back to top-quantile sustained estimated power."""
    row = con.execute("""
        WITH clean AS (
            SELECT activity_id, t_s, heartrate, watts_est
            FROM streams
            WHERE moving
              AND watts_est IS NOT NULL AND isfinite(watts_est)
              AND heartrate IS NOT NULL AND isfinite(heartrate)
        ), win AS (
            SELECT activity_id, t_s,
                   avg(watts_est) OVER w AS p20,
                   avg(heartrate) OVER w AS hr20
            FROM clean
            WINDOW w AS (PARTITION BY activity_id ORDER BY t_s
                         ROWS BETWEEN 599 PRECEDING AND 600 FOLLOWING)
        )
        SELECT max(p20) FROM win
        WHERE hr20 BETWEEN ? AND ?
    """, [lthr - 5, lthr + 5]).fetchone()
    if row and row[0] and row[0] == row[0]:
        return float(row[0])
    # fallback
    row = con.execute("""
        SELECT quantile_cont(watts_est, 0.99) FROM streams
        WHERE moving AND isfinite(watts_est)
    """).fetchone()
    return float(row[0]) if row and row[0] and row[0] == row[0] else 0.0


def detect(refit_metrics: bool = True) -> dict:
    con = warehouse.connect()
    warehouse.init(con)
    lthr, rh = detect_lthr(con)
    ftp = detect_ftp_est(con, lthr)
    print(f"Detected: LTHR={lthr}, resting={rh}, FTP-est={ftp:.0f}W")
    con.execute("""
        INSERT INTO thresholds (as_of_date, lthr, resting_hr, ftp_est_w, method)
        VALUES (current_date, ?, ?, ?, 'best-20min-hr+physics')
    """, [lthr, rh, ftp])

    if refit_metrics:
        # Recompute hrTSS for every ride with new LTHR
        con.execute("""
            UPDATE rides
            SET hrtss = (moving_s / 3600.0) *
                        pow(((avg_hr - ?) / (? - ?))::DOUBLE, 2) * 100.0
            WHERE avg_hr IS NOT NULL AND avg_hr > ?
        """, [rh, lthr, rh, rh])
        warehouse.rebuild_daily_load(con)
        print("Refit hrTSS + rebuilt daily_load")

    con.close()
    return {"lthr": lthr, "resting_hr": rh, "ftp_est_w": ftp}


if __name__ == "__main__":
    detect()
