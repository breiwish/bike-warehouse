-- bike-warehouse DuckDB schema
-- Idempotent: safe to re-run

CREATE TABLE IF NOT EXISTS rides (
    activity_id      BIGINT PRIMARY KEY,
    name             VARCHAR,
    start_date_utc   TIMESTAMP,
    start_date_local TIMESTAMP,
    timezone         VARCHAR,
    type             VARCHAR,
    sport_type       VARCHAR,
    -- summary
    distance_km      DOUBLE,
    moving_s         INTEGER,
    elapsed_s        INTEGER,
    elev_gain_m      DOUBLE,
    avg_speed_kmh    DOUBLE,
    max_speed_kmh    DOUBLE,
    avg_hr           DOUBLE,
    max_hr           DOUBLE,
    avg_cad          DOUBLE,
    -- weather (when present)
    avg_temp_c       DOUBLE,
    -- computed
    hrtss            DOUBLE,
    trimp            DOUBLE,
    ef               DOUBLE,
    decoupling_pct   DOUBLE,
    np_est_w         DOUBLE,
    avg_watts_est    DOUBLE,
    vam_mph          DOUBLE,
    z1_s INTEGER, z2_s INTEGER, z3_s INTEGER, z4_s INTEGER, z5_s INTEGER,
    -- gear dist as struct
    gear_pct         DOUBLE[],
    -- bookkeeping
    has_streams      BOOLEAN,
    ingested_at      TIMESTAMP DEFAULT now(),
    raw_path         VARCHAR
);

CREATE INDEX IF NOT EXISTS idx_rides_date ON rides(start_date_local);

-- Time-series of detected thresholds
CREATE TABLE IF NOT EXISTS thresholds (
    detected_at TIMESTAMP DEFAULT now(),
    as_of_date  DATE,
    lthr        INTEGER,
    resting_hr  INTEGER,
    ftp_est_w   DOUBLE,
    cda_fit     DOUBLE,
    crr_fit     DOUBLE,
    method      VARCHAR
);

-- Daily training load (CTL/ATL/TSB)
CREATE TABLE IF NOT EXISTS daily_load (
    date    DATE PRIMARY KEY,
    tss     DOUBLE,
    ctl     DOUBLE,  -- 42-day exp avg
    atl     DOUBLE,  -- 7-day exp avg
    tsb     DOUBLE   -- ctl - atl
);

-- View over Parquet streams; rebuilt by warehouse.build()
-- (Created dynamically from src/warehouse.py using glob path)
