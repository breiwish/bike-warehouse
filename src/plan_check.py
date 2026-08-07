"""Plan-vs-actual tracker for the 2026 summer block (6/1 -> 9/30).

Goal history:
  - Started 1200 mi.
  - 2026-07-07: cut to 1000 after a knee injury cost wk5-6.
  - 2026-07-18: reframed after a THIRD down week. Mileage stopped being the
    primary goal — it demotivated at low CTL. Anchors: (1) consistency, ride
    3x/week; (2) event = Tour de Menlo 65 mi (Sep 26). Century dropped.
  - 2026-07-18 (same day, later): user re-motivated, wanted to go harder. Picked
    the "Solid" ramp — weekly volume climbs to a ~72 mi peak, landing ~900 mi.
    Mt. Diablo back as a real option (wk11). Guardrails stay (cadence, recovery
    weeks, sharp-pain-stops); it's the *jump* that re-injures, not the number.
    Century stays dropped. GOAL_MILES = 900 (still secondary to consistency+TdM).
Weeks 1-5 keep their original targets (historical); wk6 onward is the knee-safe,
long-ride-to-65 ramp.

Single source of truth for the weekly targets lives in PLAN below. Run any time
to see where you stand against plan + whether to adjust:

    .venv/bin/python -m src.plan_check
    .venv/bin/python -m src.plan_check --asof 2026-07-15   # pretend it's that day

Reads data/warehouse.duckdb read-only (auto-ingests from Strava daily via the
GitHub Actions cron), so a fresh chat can always get current status by running
this. Companion human-readable doc: training-plan-2026.md.
"""
from __future__ import annotations

import argparse
from datetime import date, datetime, timedelta

from . import warehouse

KM_PER_MI = 1.609344
GOAL_MILES = 900  # secondary/beatable marker; real goal = consistency + Tour de Menlo 65mi
GOAL_START = date(2026, 6, 1)
GOAL_END = date(2026, 9, 30)

# week, start (Mon), end (Sun), target miles, long-ride miles, milestone, test
PLAN = [
    (1,  date(2026, 6, 1),  date(2026, 6, 7),  55, 25, "Base",             "Full Frontal"),
    (2,  date(2026, 6, 8),  date(2026, 6, 14), 60, 30, "Base",             ""),
    (3,  date(2026, 6, 15), date(2026, 6, 21), 66, 35, "Base",             ""),
    (4,  date(2026, 6, 22), date(2026, 6, 28), 48, 22, "Recovery",         ""),
    (5,  date(2026, 6, 29), date(2026, 7, 5),  70, 40, "MAP build",        ""),
    (6,  date(2026, 7, 6),  date(2026, 7, 12), 25, 12, "Re-entry (knee)",  ""),
    (7,  date(2026, 7, 13), date(2026, 7, 19), 40, 24, "Comeback ramp",    ""),
    (8,  date(2026, 7, 20), date(2026, 7, 26), 45, 28, "Rebuild + bike fit", ""),
    (9,  date(2026, 7, 27), date(2026, 8, 2),  55, 35, "Base rebuild",     ""),
    (10, date(2026, 8, 3),  date(2026, 8, 9),  62, 42, "Long-ride build",  ""),
    (11, date(2026, 8, 10), date(2026, 8, 16), 68, 48, "Diablo option",    ""),
    (12, date(2026, 8, 17), date(2026, 8, 23), 50, 32, "Recovery",         "Full Frontal"),
    (13, date(2026, 8, 24), date(2026, 8, 30), 68, 52, "Long-ride build",  ""),
    (14, date(2026, 8, 31), date(2026, 9, 6),  72, 58, "Peak long ride",   ""),
    (15, date(2026, 9, 7),  date(2026, 9, 13), 55, 45, "Taper start",      ""),
    (16, date(2026, 9, 14), date(2026, 9, 20), 60, 40, "Sharpen",          ""),
    (17, date(2026, 9, 21), date(2026, 9, 27), 65, 65, "Tour de Menlo",    ""),
    # 9/28-9/30 mop-up (~10 mi); mileage secondary (~900 target) — see docstring
]
PLAN_TOTAL = sum(w[3] for w in PLAN)


def _actual_miles(con, start: date, end: date) -> tuple[float, float]:
    """(total_mi, trainer_mi) for rides with start_date_local in [start, end]."""
    row = con.execute(
        """
        SELECT
            COALESCE(SUM(distance_km), 0) / ? AS mi,
            COALESCE(SUM(CASE WHEN trainer OR sport_type = 'VirtualRide'
                              THEN distance_km ELSE 0 END), 0) / ? AS trainer_mi
        FROM rides
        WHERE CAST(start_date_local AS DATE) BETWEEN ? AND ?
        """,
        [KM_PER_MI, KM_PER_MI, start, end],
    ).fetchone()
    return float(row[0]), float(row[1])


def _longest_ride(con, start: date, end: date) -> float:
    row = con.execute(
        """
        SELECT COALESCE(MAX(distance_km), 0) / ?
        FROM rides
        WHERE CAST(start_date_local AS DATE) BETWEEN ? AND ?
        """,
        [KM_PER_MI, start, end],
    ).fetchone()
    return float(row[0])


def _fitness(con, asof: date):
    row = con.execute(
        "SELECT date, ctl, atl, tsb FROM daily_load WHERE date <= ? ORDER BY date DESC LIMIT 1",
        [asof],
    ).fetchone()
    return row  # (date, ctl, atl, tsb) or None


def _bar(frac: float, width: int = 24) -> str:
    frac = max(0.0, min(1.5, frac))
    fill = int(round(min(frac, 1.0) * width))
    over = frac > 1.0
    return ("█" * fill + "·" * (width - fill)) + ("  +" if over else "")


def run(asof: date) -> None:
    con = warehouse.connect(readonly=True)
    try:
        print(f"\n  TRAINING PLAN — status as of {asof}")
        print(f"  Goal: {GOAL_MILES} mi  {GOAL_START} -> {GOAL_END}\n")

        # ---- cumulative + pace ----
        cum_actual, cum_trainer = _actual_miles(con, GOAL_START, asof)

        # Calendar-pace target (smooth 1200 over 122 days)
        total_days = (GOAL_END - GOAL_START).days + 1
        days_elapsed = max(0, min(total_days, (asof - GOAL_START).days + 1))
        pace_target = GOAL_MILES * days_elapsed / total_days

        # Plan-pace target (prorate the current week, sum prior full weeks)
        plan_target = 0.0
        for _, ws, we, mi, *_ in PLAN:
            if we < asof:
                plan_target += mi
            elif ws <= asof <= we:
                done = (asof - ws).days + 1
                plan_target += mi * done / 7.0
        plan_target = round(plan_target, 1)

        delta_pace = cum_actual - pace_target
        delta_plan = cum_actual - plan_target
        tshare = (cum_trainer / cum_actual * 100) if cum_actual else 0.0

        print(f"  Miles ridden:   {cum_actual:6.1f}  ({tshare:.0f}% trainer/virtual)")
        print(f"  Calendar pace:  {pace_target:6.1f}   -> {_sign(delta_pace)} mi vs even 10/day")
        print(f"  Plan pace:      {plan_target:6.1f}   -> {_sign(delta_plan)} mi vs periodized plan")
        proj = (cum_actual / days_elapsed * total_days) if days_elapsed else 0
        print(f"  Projected 9/30: {proj:6.0f} mi  ({_sign(proj - GOAL_MILES)} vs {GOAL_MILES} goal)\n")

        # ---- fitness ----
        fit = _fitness(con, asof)
        if fit:
            d, ctl, atl, tsb = fit
            ramp = _ctl_ramp(con, asof)
            flag = "  ⚠ ramping hot" if ramp is not None and ramp > 7 else ""
            print(f"  Fitness ({d}):  CTL {ctl:.0f}  ATL {atl:.0f}  TSB {tsb:+.0f}"
                  f"   7d CTL ramp {_sign(ramp) if ramp is not None else 'n/a'}{flag}\n")

        # ---- week-by-week (elapsed + current) ----
        print("  Wk  Dates            Plan  Actual   Long(plan/act)  Phase")
        print("  " + "-" * 64)
        for wk, ws, we, mi, long_mi, milestone, test in PLAN:
            if ws > asof:
                continue
            act, _ = _actual_miles(con, ws, we)
            longest = _longest_ride(con, ws, we)
            partial = "*" if ws <= asof <= we else " "
            frac = act / mi if mi else 0
            tag = f"  [{test}]" if test else ""
            print(f"  {wk:>2}{partial} {ws:%m/%d}-{we:%m/%d}  {mi:>4}  {act:>6.1f}   "
                  f"{long_mi:>3}/{longest:>4.0f}        {milestone}{tag}")
            if ws <= asof <= we:
                print(f"       this week  {_bar(frac)}  {act:.0f}/{mi} mi")
        print("\n  * = current week (in progress)")

        # ---- next milestones ----
        ups = [(ws, milestone, test) for _, ws, _w, _m, _l, milestone, test in PLAN
               if ws >= asof and (milestone not in ("Base", "MAP build", "FTP build",
                                                    "Recovery", "Peak", "Sharpen") or test)]
        if ups:
            print("\n  Next up:")
            for ws, milestone, test in ups[:4]:
                label = " / ".join(x for x in (milestone, test) if x and x not in ("Base",))
                print(f"    {ws:%b %d}  {label}")
        print()
    finally:
        con.close()


def _ctl_ramp(con, asof: date):
    row = con.execute(
        "SELECT ctl FROM daily_load WHERE date <= ? ORDER BY date DESC LIMIT 1",
        [asof],
    ).fetchone()
    prev = con.execute(
        "SELECT ctl FROM daily_load WHERE date <= ? ORDER BY date DESC LIMIT 1",
        [asof - timedelta(days=7)],
    ).fetchone()
    if row and prev and row[0] is not None and prev[0] is not None:
        return round(row[0] - prev[0], 1)
    return None


def _sign(x) -> str:
    if x is None:
        return "n/a"
    return f"{x:+.1f}"


def main() -> None:
    ap = argparse.ArgumentParser(description="Plan-vs-actual for the 2026 summer block")
    ap.add_argument("--asof", help="YYYY-MM-DD; defaults to today")
    args = ap.parse_args()
    asof = datetime.strptime(args.asof, "%Y-%m-%d").date() if args.asof else date.today()
    run(asof)


if __name__ == "__main__":
    main()
