"""Strava API client with token refresh + rate-limit aware."""
import json
import time

import requests

from .config import SECRETS

TOKEN_URL = "https://www.strava.com/oauth/token"
API = "https://www.strava.com/api/v3"
STREAM_KEYS = "time,latlng,altitude,velocity_smooth,cadence,heartrate,watts,grade_smooth,distance,moving,temp"

# Strava limits: 100 req / 15 min, 1000 / day
SHORT_LIMIT = 100
DAY_LIMIT = 1000
WINDOW_S = 15 * 60


class RateLimit:
    def __init__(self):
        self.short_used = 0
        self.day_used = 0
        self.window_start = time.time()
        self.day_start = time.time()

    def note(self, resp):
        h = resp.headers.get("X-RateLimit-Usage")
        if h:
            s, d = h.split(",")
            self.short_used, self.day_used = int(s), int(d)

    def wait_if_needed(self):
        now = time.time()
        if now - self.window_start > WINDOW_S:
            self.window_start = now
            self.short_used = 0
        if self.short_used >= SHORT_LIMIT - 2:
            sleep_s = WINDOW_S - (now - self.window_start) + 5
            print(f"[rate] short-window full, sleep {sleep_s:.0f}s")
            time.sleep(max(sleep_s, 10))
            self.window_start = time.time()
            self.short_used = 0
        if self.day_used >= DAY_LIMIT - 5:
            raise RuntimeError(f"Daily Strava limit reached ({self.day_used}). Resume tomorrow.")


_rl = RateLimit()


def _load():
    return json.loads((SECRETS / "strava.json").read_text())


def _save(c):
    (SECRETS / "strava.json").write_text(json.dumps(c, indent=2))


def access_token() -> str:
    c = _load()
    if c.get("access_token") and c.get("expires_at", 0) > time.time() + 60:
        return c["access_token"]
    if not c.get("refresh_token"):
        raise RuntimeError("No refresh_token. Run bike-report/src/oauth.py first.")
    r = requests.post(TOKEN_URL, data={
        "client_id": c["client_id"],
        "client_secret": c["client_secret"],
        "refresh_token": c["refresh_token"],
        "grant_type": "refresh_token",
    })
    r.raise_for_status()
    tok = r.json()
    c.update(refresh_token=tok["refresh_token"],
             access_token=tok["access_token"],
             expires_at=tok["expires_at"])
    _save(c)
    return c["access_token"]


def _get(path: str, **params) -> requests.Response:
    _rl.wait_if_needed()
    hdr = {"Authorization": f"Bearer {access_token()}"}
    r = requests.get(f"{API}{path}", headers=hdr, params=params, timeout=30)
    _rl.note(r)
    if r.status_code == 429:
        print("[rate] 429 received, sleeping 16min")
        time.sleep(16 * 60)
        return _get(path, **params)
    r.raise_for_status()
    return r


def list_activities(after_epoch: int | None = None,
                    before_epoch: int | None = None,
                    page: int = 1,
                    per_page: int = 100) -> list[dict]:
    params = {"per_page": per_page, "page": page}
    if after_epoch:
        params["after"] = after_epoch
    if before_epoch:
        params["before"] = before_epoch
    return _get("/athlete/activities", **params).json()


def get_activity(activity_id: int) -> dict:
    return _get(f"/activities/{activity_id}").json()


def get_streams(activity_id: int) -> dict:
    return _get(f"/activities/{activity_id}/streams",
                keys=STREAM_KEYS, key_by_type="true").json()


RIDE_TYPES = {"Ride", "VirtualRide", "GravelRide", "EBikeRide"}


def is_ride(activity: dict) -> bool:
    return activity.get("type") in RIDE_TYPES or activity.get("sport_type", "").endswith("Ride")
