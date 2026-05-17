"""Warehouse config: paths, bike spec, physics defaults.

Single-user (default):
    data/activities/, data/streams/, data/warehouse.duckdb
    secrets shared from ../bike-report/secrets

Multi-user:
    set BIKE_USER=<id> → data/users/<id>/{activities,streams,warehouse.duckdb}
    secrets at data/users/<id>/secrets/strava.json
"""
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
USER = os.environ.get("BIKE_USER")  # None = single-user default

if USER:
    DATA = ROOT / "data" / "users" / USER
    SECRETS = Path(os.environ.get("BIKE_SECRETS", DATA / "secrets"))
else:
    DATA = ROOT / "data"
    # Default secrets: local first, fall back to neighbor bike-report repo
    _local_secrets = ROOT / "secrets"
    _legacy = ROOT.parent / "bike-report" / "secrets"
    if os.environ.get("BIKE_SECRETS"):
        SECRETS = Path(os.environ["BIKE_SECRETS"])
    elif (_local_secrets / "strava.json").exists():
        SECRETS = _local_secrets
    else:
        SECRETS = _legacy

ACTIVITIES = DATA / "activities"
STREAMS = DATA / "streams"
DB_PATH = DATA / "warehouse.duckdb"

# Bike: 2020 Specialized Allez Sport
FRONT = 50
COGS = [11, 13, 15, 17, 19, 21, 23, 25, 28, 32]
RATIOS = [FRONT / c for c in COGS]
TIRE_CIRC_M = 2.105  # 700x25c

# Physics defaults (override per-ride if known)
RIDER_KG = 80.0
BIKE_KG = 9.0
CDA = 0.32          # m^2, drops on tucked Allez
CRR = 0.005         # 25c on asphalt
DRIVETRAIN_LOSS = 0.02
RHO = 1.225         # kg/m^3 sea level 15C; corrected by altitude/temp when avail
G = 9.80665

# HR
RESTING_HR = 55     # auto-refit later from min HR distribution
DEFAULT_LTHR = 170  # initial guess until detected

# TSS
HRTSS_K = 1.0       # scaling

EMAIL_TO = "ibreiwish@gmail.com"
SITE_REPO = "breiwish/bike-reports"
