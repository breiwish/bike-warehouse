"""DuckDB connection + schema + ride upsert."""
from __future__ import annotations

from pathlib import Path

import duckdb

from . import config as C


def connect(readonly: bool = False) -> duckdb.DuckDBPyConnection:
    C.DATA.mkdir(parents=True, exist_ok=True)
    return duckdb.connect(str(C.DB_PATH), read_only=readonly)


def init(con: duckdb.DuckDBPyConnection | None = None) -> None:
    own = con is None
    con = con or connect()
    schema = (Path(__file__).parent / "schema.sql").read_text()
    con.execute(schema)
    _build_stream_view(con)
    if own:
        con.close()


def _build_stream_view(con: duckdb.DuckDBPyConnection) -> None:
    # Exclude macOS AppleDouble (._*.parquet) that can leak via tar archives.
    glob = str(C.STREAMS / "[!._]*.parquet")
    existing = [p for p in C.STREAMS.glob("*.parquet")
                if not p.name.startswith("._")]
    if existing:
        con.execute(f"""
            CREATE OR REPLACE VIEW streams AS
            SELECT * FROM read_parquet('{glob}', union_by_name=true,
                                       filename=true)
        """)
    else:
        con.execute("""
            CREATE OR REPLACE VIEW streams AS
            SELECT
                CAST(NULL AS BIGINT)  AS activity_id,
                CAST(NULL AS INTEGER) AS t_s,
                CAST(NULL AS DOUBLE)  AS heartrate,
                CAST(NULL AS DOUBLE)  AS velocity_ms,
                CAST(NULL AS DOUBLE)  AS cadence_rpm,
                CAST(NULL AS DOUBLE)  AS watts,
                CAST(NULL AS DOUBLE)  AS watts_est,
                CAST(NULL AS DOUBLE)  AS grade_pct,
                CAST(NULL AS DOUBLE)  AS altitude_m,
                CAST(NULL AS DOUBLE)  AS distance_m,
                CAST(NULL AS DOUBLE)  AS temp_c,
                CAST(NULL AS BOOLEAN) AS moving,
                CAST(NULL AS DOUBLE)  AS lat,
                CAST(NULL AS DOUBLE)  AS lon
            WHERE 1=0
        """)


def upsert_ride(row: dict, con: duckdb.DuckDBPyConnection | None = None) -> None:
    own = con is None
    con = con or connect()
    cols = list(row.keys())
    placeholders = ", ".join(["?"] * len(cols))
    col_list = ", ".join(cols)
    updates = ", ".join(f"{c}=excluded.{c}" for c in cols if c != "activity_id")
    sql = f"""
        INSERT INTO rides ({col_list}) VALUES ({placeholders})
        ON CONFLICT (activity_id) DO UPDATE SET {updates}
    """
    con.execute(sql, list(row.values()))
    if own:
        con.close()


def rebuild_daily_load(con: duckdb.DuckDBPyConnection | None = None) -> None:
    """Compute CTL (42d), ATL (7d), TSB. Exp decay with TSS as input."""
    own = con is None
    con = con or connect()
    con.execute("DELETE FROM daily_load")
    # Daily TSS = sum hrtss per day
    con.execute("""
        INSERT INTO daily_load (date, tss, ctl, atl, tsb)
        WITH daily AS (
            SELECT CAST(start_date_local AS DATE) AS d, SUM(hrtss) AS tss
            FROM rides
            WHERE hrtss IS NOT NULL
            GROUP BY 1
        ),
        spine AS (
            SELECT generate_series AS d FROM generate_series(
                (SELECT MIN(d) FROM daily),
                current_date,
                INTERVAL 1 DAY
            )
        ),
        filled AS (
            SELECT s.d::DATE AS d, COALESCE(daily.tss, 0) AS tss
            FROM spine s LEFT JOIN daily USING (d)
            ORDER BY s.d
        ),
        rolled AS (
            SELECT d, tss,
                avg(tss) OVER (ORDER BY d ROWS BETWEEN 41 PRECEDING AND CURRENT ROW) AS ctl,
                avg(tss) OVER (ORDER BY d ROWS BETWEEN 6 PRECEDING AND CURRENT ROW) AS atl
            FROM filled
        )
        SELECT d, tss, ctl, atl, ctl - atl AS tsb FROM rolled
    """)
    if own:
        con.close()


def latest_lthr(con: duckdb.DuckDBPyConnection | None = None) -> int:
    own = con is None
    con = con or connect(readonly=True)
    r = con.execute("""
        SELECT lthr FROM thresholds
        ORDER BY detected_at DESC LIMIT 1
    """).fetchone()
    if own:
        con.close()
    return r[0] if r else C.DEFAULT_LTHR


def resting_hr_on(ride_date, con: duckdb.DuckDBPyConnection | None = None) -> float:
    """Best estimate of resting HR for a given date.

    Resolution order:
    1. Nearest wellness.resting_hr within ±7 days of ride_date.
    2. Rolling 30-day avg of wellness.resting_hr centered on ride_date.
    3. C.RESTING_HR constant.
    """
    own = con is None
    con = con or connect(readonly=True)
    try:
        r = con.execute("""
            SELECT resting_hr FROM wellness
            WHERE resting_hr IS NOT NULL
              AND date BETWEEN ? - INTERVAL 7 DAY AND ? + INTERVAL 7 DAY
            ORDER BY abs(date - ?) ASC
            LIMIT 1
        """, [ride_date, ride_date, ride_date]).fetchone()
        if r and r[0] is not None:
            return float(r[0])
        r = con.execute("""
            SELECT avg(resting_hr) FROM wellness
            WHERE resting_hr IS NOT NULL
              AND date BETWEEN ? - INTERVAL 30 DAY AND ? + INTERVAL 30 DAY
        """, [ride_date, ride_date]).fetchone()
        if r and r[0] is not None:
            return float(r[0])
        return float(C.RESTING_HR)
    finally:
        if own:
            con.close()


if __name__ == "__main__":
    import sys
    cmd = sys.argv[1] if len(sys.argv) > 1 else "init"
    con = connect()
    if cmd == "init":
        init(con)
        print(f"warehouse ready at {C.DB_PATH}")
    elif cmd == "build":
        init(con)
        rebuild_daily_load(con)
        n = con.execute("SELECT count(*) FROM rides").fetchone()[0]
        print(f"rides: {n}, daily_load rebuilt")
    elif cmd == "stats":
        for row in con.execute("""
            SELECT
                count(*) AS rides,
                round(sum(distance_km)::DOUBLE, 1) AS total_km,
                round(sum(elev_gain_m)::DOUBLE) AS total_climb_m,
                round(sum(hrtss)::DOUBLE) AS total_hrtss
            FROM rides
        """).fetchall():
            print(row)
    con.close()
