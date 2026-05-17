# bike-warehouse

> Local-first Strava ride warehouse + MCP server. Conversational Q&A over your training data, pre-ride prediction, weekly summaries, dashboard.

![CI](https://github.com/breiwish/bike-warehouse/actions/workflows/ci.yml/badge.svg)

## What is this

You give it your Strava OAuth credentials. It pulls every ride, computes [Performance Management Chart](https://help.trainingpeaks.com/hc/en-us/articles/204071884-Performance-Management-Chart) metrics (CTL/ATL/TSB), HR-based TSS, decoupling, efficiency factor, gear-distribution, and stores them in a local DuckDB warehouse.

Then it exposes the warehouse as a [Model Context Protocol](https://modelcontextprotocol.io) (MCP) server so you can ask Claude things like *"compare my last 5 hill rides"* or *"predict my time on this GPX at endurance pace"*.

Designed for HR-only riders (no power meter). Power is estimated from physics (Martin 1998).

## Quickstart (one ride per the maintainer)

```bash
git clone https://github.com/breiwish/bike-warehouse.git
cd bike-warehouse
python3.13 -m venv .venv && source .venv/bin/activate
pip install -r requirements-dev.txt

# 1. Create Strava API app: https://www.strava.com/settings/api
#    Set "Authorization Callback Domain" to: localhost
cp secrets/strava.example.json secrets/strava.json
# → edit secrets/strava.json, paste in client_id + client_secret

python -m src.oauth        # one-time browser auth, captures refresh_token

# 2. Pull every ride from Strava (rate-limited; takes 30-60 min for ~100 rides)
python -m src.backfill

# 3. Detect thresholds, build daily-load curve, render dashboard
python -m src.warehouse build
python -m src.thresholds
python -m src.dashboard
open site/index.html

# 4. Wire the MCP server into Claude Code
chmod +x scripts/mcp-launch.sh
claude mcp add bike-warehouse --scope user -- "$(pwd)/scripts/mcp-launch.sh"
# → restart Claude Code
```

After restart, ask Claude things like:

- *"List my rides over 50 km this year"*
- *"What's my CTL/ATL/TSB today?"*
- *"Trend my decoupling over the last 90 days"*
- *"Predict ~/Downloads/foothill.gpx at endurance pace"*
- *"Find rides where I bonked or decoupled more than 15%"*

## Even easier: ask Claude Code to set you up

This repo has a `CLAUDE.md` at the root. **Open the repo in Claude Code, then say "set me up."** Claude reads `CLAUDE.md`, walks you through Strava OAuth, runs backfill in the background, and registers the MCP server. Only step that requires you: create the Strava API app + paste in `client_id` and `client_secret`.

## Architecture

```
Strava API ──► backfill / ingest ──► data/activities/*.json
                                     data/streams/*.parquet
                                           │
                            DuckDB views ──┴──► warehouse.duckdb
                                                  │
                  ┌───────────────────────────────┼───────────────┐
                  ▼                ▼              ▼               ▼
              MCP server      dashboard       predict          summary
              (Claude Q&A)    (GH Pages)      (GPX → time)     (weekly)
```

## Why DuckDB

- **Local-first.** No server, no admin, no port. File-based — backup = copy file.
- **OLAP, columnar.** Trend queries across thousands of rides × millions of stream samples are 10-50× faster than Postgres row-store.
- **Reads Parquet natively.** Stream data lives as `data/streams/*.parquet`; DuckDB queries the directory directly. No ETL.
- **Embedded.** `import duckdb` and go.

If you ever need multi-user / network access, the SQL is portable to Postgres + Citus columnar, or push the warehouse to [MotherDuck](https://motherduck.com) for cloud DuckDB.

## Why not RAG (vector embeddings)

Ride data is **numeric and aggregate**, not narrative. RAG over markdown reports can't answer *"average decoupling on rides with >500m climbing"* — it would hallucinate. We use DuckDB SQL for numeric questions and BM25 full-text search (DuckDB FTS extension) for narrative search over ride reports. No vector store, no embeddings, no PyTorch.

## Metric definitions

| Metric | Stands for | What it tells you |
|---|---|---|
| **hrTSS** | HR-based Training Stress Score | One ride's load. 100 = 1 hour at LTHR. |
| **CTL** | Chronic Training Load | 42-day exp avg of daily TSS. *"Fitness."* |
| **ATL** | Acute Training Load | 7-day exp avg of daily TSS. *"Fatigue."* |
| **TSB** | Training Stress Balance | `CTL − ATL`. *"Form."* |
| **TRIMP** | Training Impulse (Banister) | Older HR-based load metric. |
| **EF** | Efficiency Factor | `avg_speed / avg_HR`. Rising over months = aerobic gains. |
| **Decoupling** | Pa:HR drift | % change in (speed/HR) from first half to second. >5% = HR drift / fading durability. |
| **LTHR** | Lactate Threshold HR | HR you can sustain ~1 hour. Auto-detected from your best 20-min effort across history. |
| **FTP-est** | Functional Threshold Power (estimated) | Watts equivalent of LTHR. Physics model since HR-only. |
| **VAM** | Vertical Ascent Meters/hour | Climbing fitness. |

### TSB reading guide

| TSB | Status |
|---|---|
| > +25 | Detrained |
| +5 to +25 | Fresh, race-ready |
| -10 to +5 | Productive training |
| -10 to -30 | Functional overreach (gain phase) |
| < -30 | Non-functional overreach — recover |

## MCP tools

| Tool | Use |
|---|---|
| `query_sql` | Arbitrary read-only DuckDB. Escape hatch. |
| `list_rides` | Filter by date / min distance. |
| `get_ride` | Full row for one activity. |
| `compare_rides` | Side-by-side N rides. |
| `trend` | Rolling avg of any metric. |
| `fitness_snapshot` | CTL/ATL/TSB on a date. |
| `weekly_summary` | Stats + ride list for a week. |
| `predict_ride` | GPX → predicted time/HR/load. |
| `search_reports` | BM25 over narrative reports (if bike-report neighbor present). |
| `schema` | Tables + columns dump. |

## Development

```bash
pip install -r requirements-dev.txt
pytest                          # 43 tests, ~1s
ruff check src tests            # lint
```

CI: GitHub Actions runs ruff + pytest + MCP-boot smoke test on every push/PR.

## Repo layout

```
src/
  config.py           paths, bike spec, physics defaults
  strava.py           API client (token refresh, rate-limit aware)
  oauth.py            one-time browser OAuth flow
  backfill.py         all-time history pull (resumable)
  ingest.py           single-ride loader
  schema.sql          DuckDB DDL
  warehouse.py        DB connection + view builder
  physics.py          Martin 1998 power model
  metrics.py          hrTSS, TRIMP, EF, decoupling, zones, gear dist
  thresholds.py       LTHR/FTP-est auto-detect
  reports_index.py    BM25 over narrative reports
  predict.py          GPX → predicted ride
  dashboard.py        static HTML charts
  summary.py          weekly/monthly stats
  mcp_server.py       MCP stdio server
  users.py            multi-tenant helpers (BIKE_USER env)
scripts/
  mcp-launch.sh       wrapper that cd's to repo + execs python
  weekly_summary_routine.py  cloud-routine version (no warehouse needed)
  ROUTINES.md         Claude routine setup guide
tests/
  test_physics.py, test_metrics.py, test_warehouse.py, test_ingest.py,
  test_thresholds.py, test_reports_index.py, test_mcp_server.py
.github/workflows/ci.yml
```

## Companion repo

[`bike-report`](https://github.com/breiwish/bike-report) — auto-generates per-ride markdown reports + emails them. If you clone both side-by-side, new rides auto-ingest into the warehouse via a hook in bike-report's pipeline. No extra setup.

## License

MIT
