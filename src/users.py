"""Multi-user helpers. Each user gets isolated data dir + secrets.

Usage:
    export BIKE_USER=ibreiwish
    python -m src.users init     # creates dirs, prompts for Strava OAuth
    python -m src.users list
"""
from __future__ import annotations

import json
from pathlib import Path

from . import config as C


def user_dir(user_id: str) -> Path:
    return C.ROOT / "data" / "users" / user_id


def list_users() -> list[str]:
    base = C.ROOT / "data" / "users"
    if not base.exists():
        return []
    return sorted(p.name for p in base.iterdir() if p.is_dir())


def init_user(user_id: str) -> Path:
    d = user_dir(user_id)
    for sub in ("activities", "streams", "secrets"):
        (d / sub).mkdir(parents=True, exist_ok=True)
    # Seed strava.json template if missing
    sj = d / "secrets" / "strava.json"
    if not sj.exists():
        sj.write_text(json.dumps({
            "client_id": "",
            "client_secret": "",
            "refresh_token": "",
            "access_token": "",
            "expires_at": 0,
        }, indent=2))
    print(f"User {user_id} dir → {d}")
    print(f"Fill {sj} then: BIKE_USER={user_id} python -m src.backfill")
    return d


if __name__ == "__main__":
    import sys
    cmd = sys.argv[1] if len(sys.argv) > 1 else "list"
    if cmd == "list":
        for u in list_users():
            print(u)
    elif cmd == "init":
        init_user(sys.argv[2])
    else:
        print("usage: users {list|init <id>}")
