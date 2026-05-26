"""Idempotent schema migrations applied at warehouse init time.

Each migration must be safe to re-run on any state of the DB (fresh or
already-migrated). Called from warehouse.init() after schema.sql executes,
so columns added via ALTER are guaranteed to also exist in fresh DBs (via
schema.sql) — these migrations exist purely to upgrade pre-existing DBs
that predate the schema change.
"""
from __future__ import annotations

import json
from pathlib import Path

import duckdb

from . import config as C


def _table_columns(con: duckdb.DuckDBPyConnection, table: str) -> set[str]:
    return {r[0] for r in con.execute(f"DESCRIBE {table}").fetchall()}


def _add_gear_trainer_columns(con: duckdb.DuckDBPyConnection) -> None:
    """Add gear_id/gear_name/trainer/commute to rides if missing, then backfill
    them from the raw activity JSONs on disk.

    Idempotent: only ALTERs missing columns and only updates rows where the
    target columns are still NULL.
    """
    cols = _table_columns(con, "rides")
    to_add = [
        ("gear_id", "VARCHAR"),
        ("gear_name", "VARCHAR"),
        ("trainer", "BOOLEAN"),
        ("commute", "BOOLEAN"),
    ]
    added: list[str] = []
    for name, typ in to_add:
        if name not in cols:
            con.execute(f"ALTER TABLE rides ADD COLUMN {name} {typ}")
            added.append(name)

    # Backfill any rows where any of the four columns is NULL. New ALTERs
    # default to NULL so this picks them up; for already-populated rows it's
    # a no-op.
    rows = con.execute("""
        SELECT activity_id, raw_path FROM rides
        WHERE gear_id IS NULL
           OR gear_name IS NULL
           OR trainer IS NULL
           OR commute IS NULL
    """).fetchall()
    if not rows:
        return

    activities_dir = Path(C.ACTIVITIES)
    updated = 0
    for aid, raw_path in rows:
        # Prefer the canonical activities dir; fall back to raw_path with
        # cross-host prefix rewrites (e.g. dev VM vs GH Actions runner).
        p = activities_dir / f"{aid}.json"
        if not p.exists() and raw_path:
            cand = Path(raw_path)
            if cand.exists():
                p = cand
            else:
                # Try swapping common prefixes onto the local activities dir.
                for pre in (
                    "/Users/irb/dev/bike-warehouse/",
                    "/home/runner/work/bike-warehouse/bike-warehouse/",
                ):
                    if raw_path.startswith(pre):
                        rebased = Path(str(activities_dir.parent.parent)) / raw_path[len(pre):]
                        if rebased.exists():
                            p = rebased
                            break
        if not p.exists():
            continue
        try:
            a = json.loads(p.read_text())
        except Exception:
            continue
        g = a.get("gear") or {}
        con.execute(
            "UPDATE rides SET gear_id = ?, gear_name = ?, "
            "trainer = ?, commute = ? WHERE activity_id = ?",
            [
                a.get("gear_id"),
                g.get("name"),
                bool(a.get("trainer")),
                bool(a.get("commute")),
                aid,
            ],
        )
        updated += 1
    if added or updated:
        print(f"migrations: gear/trainer added={added} backfilled={updated} rows")


def _add_calories_column(con: duckdb.DuckDBPyConnection) -> None:
    """Add calories to rides if missing, then backfill from raw activity JSONs.

    Idempotent: only ALTERs when missing and only updates rows where calories
    is still NULL. Strava exposes `calories` only on the detailed activity
    payload (already cached in data/activities/*.json), so no API calls.
    """
    cols = _table_columns(con, "rides")
    if "calories" not in cols:
        con.execute("ALTER TABLE rides ADD COLUMN calories DOUBLE")

    rows = con.execute("""
        SELECT activity_id, raw_path FROM rides WHERE calories IS NULL
    """).fetchall()
    if not rows:
        return

    activities_dir = Path(C.ACTIVITIES)
    updated = 0
    for aid, raw_path in rows:
        p = activities_dir / f"{aid}.json"
        if not p.exists() and raw_path:
            cand = Path(raw_path)
            if cand.exists():
                p = cand
            else:
                for pre in (
                    "/Users/irb/dev/bike-warehouse/",
                    "/home/runner/work/bike-warehouse/bike-warehouse/",
                ):
                    if raw_path.startswith(pre):
                        rebased = Path(str(activities_dir.parent.parent)) / raw_path[len(pre):]
                        if rebased.exists():
                            p = rebased
                            break
        if not p.exists():
            continue
        try:
            a = json.loads(p.read_text())
        except Exception:
            continue
        cal = a.get("calories")
        if cal is None:
            continue
        con.execute(
            "UPDATE rides SET calories = ? WHERE activity_id = ?", [cal, aid]
        )
        updated += 1
    if updated:
        print(f"migrations: calories backfilled={updated} rows")


MIGRATIONS = [
    _add_gear_trainer_columns,
    _add_calories_column,
]


def apply_all(con: duckdb.DuckDBPyConnection) -> None:
    for m in MIGRATIONS:
        m(con)
