# Claude Code instructions for bike-warehouse

When the user clones this repo and opens it in Claude Code, **proactively offer
to set them up.** They want the same thing the maintainer built: a local DuckDB
warehouse of their Strava rides plus an MCP server to query it conversationally.

## Setup playbook

Run these in order. Stop and ask the user only at the steps marked **STOP**.

### 1. Sanity check + venv

```bash
python3.13 -m venv .venv          # or whichever 3.13+ is available
.venv/bin/pip install --upgrade pip
.venv/bin/pip install -r requirements-dev.txt
```

If Python 3.13 is not installed, tell the user to install via Homebrew
(`brew install python@3.13`) or pyenv. **Don't** silently fall back to 3.11/3.12;
DuckDB + polars versions are pinned to 3.13.

### 2. Strava API app — **STOP, requires user**

The user must create a Strava API app at
[strava.com/settings/api](https://www.strava.com/settings/api). Tell them:

- Application name: anything
- Category: Data Importer
- Website: anything (e.g. `https://localhost`)
- **Authorization Callback Domain: `localhost`** (this is the critical setting)

Once created, copy `client_id` and `client_secret` from the API page.

### 3. Drop creds into secrets file

```bash
cp secrets/strava.example.json secrets/strava.json
```

Edit `secrets/strava.json` and paste in `client_id` + `client_secret`. Leave
other fields as-is.

### 4. OAuth one-time flow

```bash
.venv/bin/python -m src.oauth
```

Opens browser, user authorizes, captures refresh_token. Stores it in
`secrets/strava.json`. **One-time.**

### 5. Backfill all rides — **long-running, run in background**

```bash
nohup .venv/bin/python -u -m src.backfill > data/backfill.log 2>&1 &
```

Strava rate-limited to 100 requests / 15 min. ~100 rides ≈ 30-60 min total
(includes mandatory rate-limit cooldowns).

Show the user progress: `tail -f data/backfill.log` or
`grep -c "→ warehouse" data/backfill.log`.

### 6. Detect thresholds + build daily-load curve

```bash
.venv/bin/python -m src.warehouse build       # rebuild stream view + daily_load
.venv/bin/python -m src.thresholds            # auto-detect LTHR + FTP-est
```

### 7. Generate dashboard

```bash
.venv/bin/python -m src.dashboard
open site/index.html
```

### 8. Register MCP server in Claude Code

```bash
chmod +x scripts/mcp-launch.sh
claude mcp add bike-warehouse --scope user -- "$(pwd)/scripts/mcp-launch.sh"
```

Then tell the user: **"Restart Claude Code so the MCP server loads."** After
restart, `/mcp` should show `bike-warehouse: connected`.

### 9. Smoke test

Ask the user to try a conversational query in Claude Code, e.g.:

- *"List my rides over 50 km this year"*
- *"What's my fitness today?"*
- *"Show me decoupling trend last 90 days"*

## Auto-ingest from sister repo

If the user also has [`bike-report`](https://github.com/breiwish/bike-report)
cloned next to this repo, the bike-report pipeline auto-pushes new rides into
the warehouse via `maybe_ingest_warehouse()` in `bike-report/src/run_pipeline.py`.
No action needed; just keep both repos installed side-by-side.

## Repo conventions

- **Caveman caveat:** maintainer uses terse caveman tone; don't mimic in commits
  or PRs (use normal English).
- **Always run tests before committing:** `pytest`
- **Always lint before committing:** `ruff check src tests`
- **Never commit:** `data/`, `secrets/*.json` (except `*.example.json`),
  `*.duckdb`, `site/`. `.gitignore` covers these.

## Architecture cheat-sheet

```
Strava API ──► src/backfill.py / src/ingest.py
                    │
                    ▼
              data/activities/*.json      (raw API responses)
              data/streams/*.parquet      (per-second HR/cad/grade/watts_est)
              data/warehouse.duckdb       (one row per ride + computed metrics)
                    │
        ┌───────────┴───────────┬──────────────┬───────────────┐
        ▼                       ▼              ▼               ▼
   src/mcp_server.py    src/dashboard.py  src/predict.py  src/summary.py
   (Claude Q&A)         (static HTML)     (GPX → time)    (weekly narrative)
```

## Tables (DuckDB)

| Table | Purpose |
|---|---|
| `rides` | One row per Strava ride: summary + computed metrics (hrTSS, EF, decoupling, NP-est, zones, gear histogram). |
| `streams` | View over Parquet files: per-second HR, speed, cadence, watts_est, etc. |
| `thresholds` | Time-series of detected LTHR / FTP-est. |
| `daily_load` | Per-day CTL / ATL / TSB curve. Extends to current date. |
| `reports` | Optional: indexed `bike-report` narrative markdowns for BM25 search. |

## MCP tools

| Tool | Purpose |
|---|---|
| `query_sql` | Arbitrary read-only DuckDB query. Use when no other tool fits. |
| `list_rides` | Filter by date range / min distance. |
| `get_ride` | Full row for one activity. |
| `compare_rides` | Side-by-side N rides. |
| `trend` | Rolling avg of a metric (hrtss, ef, decoupling_pct, vam_mph, ...). |
| `fitness_snapshot` | CTL/ATL/TSB on a date. |
| `weekly_summary` | Stats + ride list for a week. |
| `predict_ride` | GPX → predicted time/HR/load. |
| `search_reports` | BM25 over narrative reports (if bike-report neighbor present). |
| `schema` | DuckDB schema dump. |

## Common questions Claude should be able to answer

- "How is my fitness trending?" → query `daily_load` for CTL over last 90d
- "Compare my hardest 3 rides this year" → top hrTSS + `compare_rides`
- "Am I getting faster on flat rides?" → `ef` trend filtered by `elev_gain_m < 100`
- "Predict my time for this GPX at endurance pace" → `predict_ride`
- "What does TSB -15 mean?" → cite the table in CLAUDE.md / README
