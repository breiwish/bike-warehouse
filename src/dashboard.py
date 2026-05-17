"""Static HTML dashboard: CTL/ATL/TSB, weekly TSS, LTHR trend, decoupling, gear use."""
from __future__ import annotations

import matplotlib

matplotlib.use("Agg")
import matplotlib.dates as mdates
import matplotlib.pyplot as plt
import numpy as np

from . import config as C
from . import warehouse

OUT = C.ROOT / "site"


def _save(fig, name):
    OUT.mkdir(parents=True, exist_ok=True)
    p = OUT / name
    fig.savefig(p, dpi=110, bbox_inches="tight")
    plt.close(fig)
    return p


def chart_pmc():
    con = warehouse.connect(readonly=True)
    df = con.execute("""
        SELECT date, tss, ctl, atl, tsb FROM daily_load ORDER BY date
    """).fetchnumpy()
    con.close()
    if len(df["date"]) == 0:
        return None
    fig, ax = plt.subplots(figsize=(11, 4))
    ax.fill_between(df["date"], 0, df["tss"], alpha=0.25, label="Daily TSS")
    ax.plot(df["date"], df["ctl"], color="C2", lw=2, label="CTL (fitness)")
    ax.plot(df["date"], df["atl"], color="C3", lw=1, label="ATL (fatigue)")
    ax2 = ax.twinx()
    ax2.plot(df["date"], df["tsb"], color="C0", lw=1, alpha=0.6, label="TSB (form)")
    ax2.axhline(0, color="k", lw=0.5)
    ax.set_title("Performance Management Chart")
    ax.set_xlabel("")
    ax.set_ylabel("TSS / day")
    ax2.set_ylabel("TSB")
    ax.legend(loc="upper left", fontsize=8)
    ax2.legend(loc="upper right", fontsize=8)
    ax.xaxis.set_major_locator(mdates.AutoDateLocator())
    return _save(fig, "pmc.png")


def chart_lthr_trend():
    con = warehouse.connect(readonly=True)
    rows = con.execute("""
        SELECT as_of_date, lthr, ftp_est_w FROM thresholds ORDER BY as_of_date
    """).fetchall()
    con.close()
    if not rows:
        return None
    fig, ax = plt.subplots(figsize=(9, 3))
    dates = [r[0] for r in rows]
    ax.plot(dates, [r[1] for r in rows], "o-", label="LTHR")
    ax2 = ax.twinx()
    ax2.plot(dates, [r[2] for r in rows], "s-", color="C1", label="FTP-est (W)")
    ax.set_title("Threshold trend (auto-detected)")
    ax.legend(loc="upper left")
    ax2.legend(loc="upper right")
    return _save(fig, "lthr_trend.png")


def chart_decoupling():
    con = warehouse.connect(readonly=True)
    rows = con.execute("""
        SELECT start_date_local, decoupling_pct
        FROM rides WHERE decoupling_pct IS NOT NULL
        ORDER BY start_date_local
    """).fetchall()
    con.close()
    if not rows:
        return None
    dates = [r[0] for r in rows]
    dec = [r[1] for r in rows]
    fig, ax = plt.subplots(figsize=(11, 3.5))
    ax.axhline(0, color="k", lw=0.5)
    ax.axhline(-5, color="g", lw=0.5, ls="--", alpha=0.5)
    ax.bar(dates, dec, width=2,
           color=["C2" if d > -5 else "C3" for d in dec])
    ax.set_title("Aerobic decoupling per ride (more negative = worse durability)")
    ax.set_ylabel("Decoupling %")
    return _save(fig, "decoupling.png")


def chart_weekly_tss():
    con = warehouse.connect(readonly=True)
    rows = con.execute("""
        SELECT date_trunc('week', date) AS wk, sum(tss) AS tss
        FROM daily_load GROUP BY 1 ORDER BY 1
    """).fetchall()
    con.close()
    if not rows:
        return None
    fig, ax = plt.subplots(figsize=(11, 3))
    ax.bar([r[0] for r in rows], [r[1] for r in rows], width=5)
    ax.set_title("Weekly hrTSS")
    return _save(fig, "weekly_tss.png")


def chart_gear_use():
    con = warehouse.connect(readonly=True)
    rows = con.execute("""
        SELECT start_date_local, gear_pct
        FROM rides WHERE gear_pct IS NOT NULL
        ORDER BY start_date_local
    """).fetchall()
    con.close()
    if not rows:
        return None
    mat = np.array([r[1] for r in rows]).T  # gears x rides
    fig, ax = plt.subplots(figsize=(11, 4))
    ax.imshow(mat, aspect="auto", origin="lower", cmap="viridis")
    ax.set_yticks(range(len(C.COGS)))
    ax.set_yticklabels([f"50×{c}" for c in C.COGS])
    ax.set_title("Gear distribution over time (%)")
    return _save(fig, "gear_use.png")


def build_index():
    summary = warehouse.connect(readonly=True).execute("""
        SELECT count(*) rides,
               round(sum(distance_km), 1) km,
               round(sum(elev_gain_m)) climb_m,
               round(sum(hrtss)) total_hrtss,
               round(avg(ef), 2) avg_ef,
               round(avg(decoupling_pct), 1) avg_decoup
        FROM rides
    """).fetchone()

    html = f"""<!doctype html>
<html><head><title>bike-warehouse dashboard</title>
<style>body{{font-family:system-ui;max-width:1100px;margin:2em auto;padding:0 1em}}
img{{max-width:100%;display:block;margin:1em 0;border:1px solid #ddd}}</style></head>
<body>
<h1>Body of work</h1>
<p>Rides: <b>{summary[0]}</b> · Distance: <b>{summary[1]} km</b> ·
   Climb: <b>{summary[2]} m</b> · Total hrTSS: <b>{summary[3]}</b> ·
   Avg EF: <b>{summary[4]}</b> · Avg decoupling: <b>{summary[5]}%</b></p>
<h2>Performance Management</h2><img src="pmc.png">
<h2>Weekly TSS</h2><img src="weekly_tss.png">
<h2>Threshold trend</h2><img src="lthr_trend.png">
<h2>Decoupling per ride</h2><img src="decoupling.png">
<h2>Gear use over time</h2><img src="gear_use.png">
</body></html>"""
    (OUT / "index.html").write_text(html)
    print(f"dashboard → {OUT/'index.html'}")


def build_all():
    for fn in [chart_pmc, chart_weekly_tss, chart_lthr_trend,
               chart_decoupling, chart_gear_use]:
        try:
            fn()
        except Exception as e:
            print(f"  {fn.__name__} failed: {e}")
    build_index()


if __name__ == "__main__":
    build_all()
