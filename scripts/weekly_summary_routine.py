#!/usr/bin/env python3
"""Self-contained weekly summary for Claude cloud routine.

Reads Strava direct (no local warehouse needed). Emails summary via Gmail SMTP.

Required env vars:
    STRAVA_CLIENT_ID
    STRAVA_CLIENT_SECRET
    STRAVA_REFRESH_TOKEN
    GMAIL_ADDRESS
    GMAIL_APP_PASSWORD
    GMAIL_TO       (optional, defaults to GMAIL_ADDRESS)

Usage:
    python weekly_summary_routine.py [days]      # default 7
"""
from __future__ import annotations
import os
import sys
import smtplib
import ssl
import time
import json
from email.message import EmailMessage
from datetime import datetime, timedelta, timezone

import urllib.request
import urllib.parse


STRAVA_API = "https://www.strava.com/api/v3"


def _post(url: str, data: dict) -> dict:
    body = urllib.parse.urlencode(data).encode()
    req = urllib.request.Request(url, data=body, method="POST")
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read())


def _get(path: str, token: str, **params) -> list | dict:
    qs = urllib.parse.urlencode(params)
    url = f"{STRAVA_API}{path}?{qs}"
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {token}"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read())


def fresh_token() -> str:
    tok = _post("https://www.strava.com/oauth/token", {
        "client_id": os.environ["STRAVA_CLIENT_ID"],
        "client_secret": os.environ["STRAVA_CLIENT_SECRET"],
        "refresh_token": os.environ["STRAVA_REFRESH_TOKEN"],
        "grant_type": "refresh_token",
    })
    return tok["access_token"]


RIDE_TYPES = {"Ride", "VirtualRide", "GravelRide", "EBikeRide"}


def fetch_rides(token: str, after_ts: int) -> list[dict]:
    page, out = 1, []
    while True:
        chunk = _get("/athlete/activities", token,
                     after=after_ts, per_page=100, page=page)
        if not chunk:
            break
        out.extend([a for a in chunk if a.get("type") in RIDE_TYPES])
        if len(chunk) < 100:
            break
        page += 1
        time.sleep(1)
    return out


def stats(rides: list[dict]) -> dict:
    if not rides:
        return {"rides": 0, "km": 0, "elev_m": 0, "hours": 0.0,
                "avg_hr": None, "avg_speed_kmh": None}
    km = sum(r.get("distance", 0) for r in rides) / 1000.0
    elev = sum(r.get("total_elevation_gain", 0) or 0 for r in rides)
    secs = sum(r.get("moving_time", 0) or 0 for r in rides)
    hr_vals = [r["average_heartrate"] for r in rides if r.get("average_heartrate")]
    spd_vals = [r["average_speed"] for r in rides if r.get("average_speed")]
    return {
        "rides": len(rides),
        "km": round(km, 1),
        "elev_m": int(elev),
        "hours": round(secs / 3600.0, 2),
        "avg_hr": round(sum(hr_vals) / len(hr_vals), 1) if hr_vals else None,
        "avg_speed_kmh": (round(sum(spd_vals) / len(spd_vals) * 3.6, 1)
                          if spd_vals else None),
    }


def format_email(week: dict, prior4: dict,
                 rides: list[dict], window_days: int) -> str:
    def cmp(cur, prev, unit=""):
        if prev is None or prev == 0 or cur is None:
            return ""
        delta = cur - prev
        pct = (delta / prev * 100) if prev else 0
        sign = "+" if delta >= 0 else ""
        return f" ({sign}{delta:.1f}{unit} vs prior {sign}{pct:+.0f}%)"

    lines = [
        f"Cycling — last {window_days} days",
        "=" * 40,
        f"Rides:    {week['rides']}{cmp(week['rides'], prior4.get('rides_per_week'))}",
        f"Distance: {week['km']} km{cmp(week['km'], prior4.get('km_per_week'), ' km')}",
        f"Climb:    {week['elev_m']} m{cmp(week['elev_m'], prior4.get('elev_per_week'), ' m')}",
        f"Time:     {week['hours']} h",
        f"Avg HR:   {week['avg_hr'] or '—'}",
        f"Avg spd:  {week['avg_speed_kmh'] or '—'} km/h",
        "",
        "Rides:",
    ]
    for r in sorted(rides, key=lambda x: x.get("start_date_local", "")):
        d = (r.get("start_date_local") or "")[:10]
        lines.append(
            f"  {d}  {r.get('name','?')[:40]:<40}  "
            f"{(r.get('distance',0)/1000):>5.1f} km  "
            f"{(r.get('total_elevation_gain') or 0):>4.0f} m  "
            f"HR {r.get('average_heartrate', '—')}"
        )
    return "\n".join(lines)


def send_mail(subject: str, body: str) -> None:
    addr = os.environ["GMAIL_ADDRESS"]
    pw = os.environ["GMAIL_APP_PASSWORD"]
    to = os.environ.get("GMAIL_TO", addr)
    msg = EmailMessage()
    msg["From"] = addr
    msg["To"] = to
    msg["Subject"] = subject
    msg.set_content(body)
    ctx = ssl.create_default_context()
    with smtplib.SMTP_SSL("smtp.gmail.com", 465, context=ctx) as s:
        s.login(addr, pw)
        s.send_message(msg)


def main(window_days: int = 7) -> None:
    token = fresh_token()
    now = int(time.time())
    week_after = now - window_days * 86400
    prior4_after = now - 28 * 86400

    rides_week = fetch_rides(token, week_after)
    rides_4w = fetch_rides(token, prior4_after)

    # Build prior 4wk averages excluding current week
    cutoff = datetime.now(timezone.utc) - timedelta(days=window_days)
    rides_prior_only = [
        r for r in rides_4w
        if datetime.fromisoformat(r["start_date"].replace("Z", "+00:00")) < cutoff
    ]
    prior_stats = stats(rides_prior_only)
    # Normalize per week
    weeks = max((28 - window_days) / 7.0, 1.0)
    prior4_per_week = {
        "rides_per_week": prior_stats["rides"] / weeks,
        "km_per_week": prior_stats["km"] / weeks,
        "elev_per_week": prior_stats["elev_m"] / weeks,
    }

    week_stats = stats(rides_week)
    body = format_email(week_stats, prior4_per_week, rides_week, window_days)
    print(body)
    if os.environ.get("GMAIL_APP_PASSWORD"):
        send_mail(f"Cycling — last {window_days} days "
                  f"({week_stats['rides']} rides, {week_stats['km']} km)", body)
        print("\n(emailed)")
    else:
        print("\n(no GMAIL_APP_PASSWORD set — skipping email)")


if __name__ == "__main__":
    days = int(sys.argv[1]) if len(sys.argv) > 1 else 7
    main(days)
