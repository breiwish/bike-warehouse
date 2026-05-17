"""Warehouse schema + upsert + daily_load + NaN scrubbing."""
import duckdb

from src import ingest, warehouse


def test_init_creates_tables(tmp_repo):
    warehouse.init()
    con = warehouse.connect(readonly=True)
    tables = {r[0] for r in con.execute(
        "SELECT table_name FROM information_schema.tables").fetchall()}
    assert {"rides", "thresholds", "daily_load"} <= tables
    con.close()


def test_upsert_ride_inserts_then_updates(tmp_repo):
    warehouse.init()
    row = {"activity_id": 1, "name": "first", "distance_km": 10.0,
           "start_date_local": "2025-08-01 08:00:00"}
    warehouse.upsert_ride(row)

    row2 = {"activity_id": 1, "name": "first-updated", "distance_km": 12.0,
            "start_date_local": "2025-08-01 08:00:00"}
    warehouse.upsert_ride(row2)

    con = warehouse.connect(readonly=True)
    rows = con.execute("SELECT name, distance_km FROM rides").fetchall()
    con.close()
    assert rows == [("first-updated", 12.0)]


def test_nan_safe_insert_rejects_nan(tmp_repo):
    """Ingest._nan_to_none should keep NaN out of DB."""
    warehouse.init()
    row = {"activity_id": 7, "name": "n", "hrtss": float("nan"),
           "start_date_local": "2025-08-01 08:00:00"}
    row = {k: ingest._nan_to_none(v) for k, v in row.items()}
    warehouse.upsert_ride(row)
    con = warehouse.connect(readonly=True)
    val = con.execute("SELECT hrtss FROM rides WHERE activity_id=7").fetchone()
    con.close()
    assert val == (None,)


def test_latest_lthr_returns_default_when_no_thresholds(tmp_repo):
    warehouse.init()
    from src import config as C
    assert warehouse.latest_lthr() == C.DEFAULT_LTHR


def test_latest_lthr_returns_inserted(tmp_repo):
    warehouse.init()
    con = warehouse.connect()
    con.execute("""INSERT INTO thresholds (as_of_date, lthr, resting_hr, ftp_est_w)
                   VALUES (current_date, 165, 50, 200)""")
    con.close()
    assert warehouse.latest_lthr() == 165


def test_daily_load_rebuilds_and_extends_to_today(synth_warehouse):
    """daily_load spine extends through current_date even if last ride was earlier."""
    import datetime
    con = duckdb.connect(str(synth_warehouse / "data" / "warehouse.duckdb"),
                          read_only=True)
    max_d = con.execute("SELECT max(date) FROM daily_load").fetchone()[0]
    con.close()
    assert max_d == datetime.date.today()
