# Claude routines for bike-warehouse

Routines run in **Claude cloud** — independent of your laptop. Trigger via the `/schedule` skill in Claude Code.

## Weekly summary routine

Runs Sundays at 8pm local, pulls last 7 days of rides from Strava, emails report.

### Setup

1. Confirm Strava + Gmail creds on file:
   - `/Users/irb/dev/bike-report/secrets/strava.json` — has `client_id`, `client_secret`, `refresh_token`
   - `/Users/irb/dev/bike-report/secrets/gmail.json` — has `address`, `app_password`

2. In Claude Code: `/schedule create` (or just ask Claude to create a routine).

3. Paste this routine prompt — **fill in the placeholder secrets first**:

```
Weekly cycling summary. Run every Sunday at 20:00 America/Los_Angeles.

Steps:
1. Write the script /tmp/weekly_summary.py with the contents of:
   https://raw.githubusercontent.com/breiwish/bike-warehouse/main/scripts/weekly_summary_routine.py
   (or paste inline — full source below)

2. Run with these env vars:
   STRAVA_CLIENT_ID=<your_id>
   STRAVA_CLIENT_SECRET=<your_secret>
   STRAVA_REFRESH_TOKEN=<your_refresh_token>
   GMAIL_ADDRESS=ibreiwish@gmail.com
   GMAIL_APP_PASSWORD=<16-char app password>

3. Command:
   STRAVA_CLIENT_ID=... GMAIL_APP_PASSWORD='xxxx xxxx xxxx xxxx' \
   python3 /tmp/weekly_summary.py 7

4. Confirm email arrived. If not, surface error in routine output.
```

### Why this works without your laptop

- Script uses only Python stdlib (no pip installs needed in routine sandbox).
- Strava OAuth refresh_token bootstraps fresh access_token on each run.
- Email sent via Gmail SMTP from cloud sandbox.
- No dependency on local DuckDB warehouse — Strava is queried directly.

### Limitations

- Doesn't compute hrTSS, CTL, decoupling — those need the local warehouse's history.
- Stats limited to: ride count, distance, elev gain, avg HR, avg speed, vs prior 4-week avg.
- If you want full-fidelity stats in the email, **option A**: push warehouse to MotherDuck (cloud DuckDB) and have routine read from there. **Option B**: laptop-side cron generates summary, routine just emails it.

## Monthly recap routine

Same shape, 30-day window. Set `window_days=30` and schedule for 1st of month at 09:00.

## Pre-ride alert routine (future)

Schedule daily 6am. Fetch user's planned route GPX from Google Calendar or Strava planned route. Call `predict_ride()`. Email predicted time/HR/pacing.

Needs:
- Source of route GPX (calendar attachment? Strava routes API?)
- Local warehouse → cloud sync for personal HR curve

## Routine maintenance

- Routines log to Claude Code transcript history — check there if email stops arriving.
- Strava refresh_token rotates on every use. Both bike-report and the routine share the same token in `secrets/strava.json`. Routine writes back updated token? **No — to keep routine stateless, give it a dedicated long-lived refresh_token by doing OAuth once with `prompt=force`.** Otherwise the local bike-report pipeline + routine will race to refresh and the loser is logged out.
