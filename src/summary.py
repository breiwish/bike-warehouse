"""Weekly / monthly narrative summaries pulled from warehouse."""
from __future__ import annotations

import json
from datetime import date, timedelta

from . import warehouse


def weekly(end: date | None = None) -> dict:
    """Stats for the week ending `end` (default today)."""
    end = end or date.today()
    start = end - timedelta(days=6)
    con = warehouse.connect(readonly=True)
    week = con.execute("""
        SELECT count(*) AS rides,
               round(sum(distance_km),1) AS km,
               round(sum(elev_gain_m)) AS climb,
               round(sum(hrtss)) AS tss,
               round(avg(ef),2) AS ef,
               round(avg(decoupling_pct),1) AS decoup,
               round(avg(avg_hr),0) AS avg_hr
        FROM rides
        WHERE CAST(start_date_local AS DATE) BETWEEN ? AND ?
    """, [start, end]).fetchone()

    prev = con.execute("""
        SELECT round(avg(distance_km),1), round(avg(hrtss),0), round(avg(ef),2)
        FROM rides
        WHERE CAST(start_date_local AS DATE) BETWEEN ? AND ?
    """, [end - timedelta(days=27), end - timedelta(days=7)]).fetchone()

    pmc = con.execute("""
        SELECT ctl, atl, tsb FROM daily_load WHERE date = ?
    """, [end]).fetchone() or (None, None, None)

    rides = con.execute("""
        SELECT name, start_date_local, distance_km, elev_gain_m,
               hrtss, decoupling_pct
        FROM rides
        WHERE CAST(start_date_local AS DATE) BETWEEN ? AND ?
        ORDER BY hrtss DESC
    """, [start, end]).fetchall()
    con.close()

    return {
        "period": f"{start} → {end}",
        "rides": week[0],
        "distance_km": week[1],
        "elev_m": week[2],
        "hrtss": week[3],
        "avg_ef": week[4],
        "avg_decoup": week[5],
        "avg_hr": week[6],
        "prior_4wk_avg_distance": prev[0],
        "prior_4wk_avg_hrtss": prev[1],
        "prior_4wk_avg_ef": prev[2],
        "ctl": round(pmc[0], 1) if pmc[0] else None,
        "atl": round(pmc[1], 1) if pmc[1] else None,
        "tsb": round(pmc[2], 1) if pmc[2] else None,
        "ride_list": [
            {"name": r[0], "date": str(r[1]), "km": r[2],
             "climb_m": r[3], "hrtss": r[4], "decoup": r[5]}
            for r in rides
        ],
    }


def render_markdown(stats: dict) -> str:
    lines = [f"# Week {stats['period']}", ""]
    lines.append(f"- Rides: **{stats['rides']}**, {stats['distance_km']} km, "
                 f"{stats['elev_m']} m climb")
    lines.append(f"- hrTSS: **{stats['hrtss']}** "
                 f"(prior 4wk avg/wk: {stats['prior_4wk_avg_hrtss'] or '?'})")
    if stats['ctl'] is not None:
        lines.append(f"- CTL **{stats['ctl']}** · ATL {stats['atl']} · "
                     f"TSB {stats['tsb']:+}")
    lines.append(f"- Avg EF {stats['avg_ef']} · "
                 f"avg decoupling {stats['avg_decoup']}%")
    lines.append("")
    lines.append("## Rides (by load)")
    for r in stats["ride_list"]:
        lines.append(f"- {r['date'][:10]} · **{r['name']}** · "
                     f"{r['km']} km / {r['climb_m']} m · "
                     f"hrTSS {r['hrtss']} · decoup {r['decoup']}%")
    return "\n".join(lines)


if __name__ == "__main__":
    s = weekly()
    print(render_markdown(s))
    print()
    print(json.dumps(s, indent=2, default=str))
