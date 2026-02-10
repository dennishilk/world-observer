![status](https://img.shields.io/badge/status-active-blue?style=flat)
![updates](https://img.shields.io/badge/updates-daily-blue?style=flat)
![language](https://img.shields.io/badge/language-python-blue?style=flat)
![license](https://img.shields.io/badge/license-MIT-gray?style=flat)
![scope](https://img.shields.io/badge/scope-observational-lightgrey?style=flat)

# World Observer

World Observer is a long-term, passive observation project focused on global
network reachability, silence, and instability. The project is designed to be
conservative and predictable: it favors consistency over novelty and prioritizes
repeatable, low-risk observations that can be sustained for years.

## Project Philosophy
- **Passive by design**: Observers rely only on publicly observable, non-invasive
  signals. No scanning, probing, exploitation, or interference.
- **Consistency over discovery**: Repeatable measurements, taken on a stable
  cadence, are more valuable than one-off findings.
- **Separation of concerns**: Observers emit JSON only. Aggregation and
  visualization are separate, downstream activities.
- **Boring and durable**: Code should be minimal, readable, and stable over time.

## Operation Cadence
### Daily
- Execute observers on a fixed schedule.
- Store raw JSON outputs in the `data/` directory.
- Ensure logs are consistent and auditable.

### Weekly
- Validate data continuity and detect missing observation windows.
- Summarize stability or instability trends without altering core observer logic.

### Long-Term
- Maintain unchanged observer semantics for comparability across years.
- Add new observers only when they meet strict passive and ethical requirements.
- Preserve the full historical record of observation outputs.

### Periodic GitHub Heartbeat
The repository publishes a minimal heartbeat as a liveness indicator only. These
hourly commits are not observation results and should not be interpreted as
signals, anomalies, or summaries.

- **Purpose**: confirm the automation is alive and pushing on schedule.
- **Frequency**: every hour.
- **Retention**: keep only the last 12 heartbeat files.

Example usage:
```sh
cat state/heartbeat/2026-02-19T14Z.json
```

Heartbeat commits:
- do **not** indicate unusual events,
- are **not** significance indicators,
- are **not** daily summaries.

## Repository Layout
- `observers/`: Passive observer modules emitting JSON.
- `data/`: Aggregated daily outputs, rolling latest snapshots, and local-only raw capture folders (ignored by Git for raw data).
- `visualizations/`: Downstream visual analysis (separate from observers).
- `reports/`: Periodic summaries and research notes.
- `scripts/`: Helper scripts for scheduling or data hygiene.
- `cron/`: Example schedules for long-running operation.

## Data Hygiene and Automation
### Raw vs Aggregated Data in Git
Raw observer output is intentionally retained on the server but ignored by Git.
The repository `.gitignore` excludes these local-only raw directories:

- `data/*-reachability/`
- `data/*-connectivity/`
- `data/*-weather/`
- `data/*-trace/`

This keeps raw capture storage available for local analysis and troubleshooting
without bloating repository history.

### Directory Layout
- `data/daily/YYYY-MM-DD/`: immutable daily aggregated JSON/summary artifacts
  intended for long-term tracking in Git.
- `data/latest/`: rolling latest aggregate snapshots in Git for quick inspection.
- `data/*-(reachability|connectivity|weather|trace)/`: raw observer output,
  generated locally and ignored by Git.

### Heartbeat and Cron Schedule
The automation layer installs two cron jobs for the observer user:

- **Hourly heartbeat at minute 0**
  - Runs `python scripts/heartbeat_push.py`.
  - Appends output to `logs/cron.log`.
- **Daily UTC run at 02:00**
  - Runs aggregation (`scripts/run_daily.py`).
  - Generates significance PNG (`visualizations/generate_significance_png.py`).
  - Stages changes, creates a date-based commit if needed, and pushes.
  - Appends output to `logs/cron.log`.

Cron entries are installed idempotently by `setup_world_observer.sh`, so
re-running setup will not duplicate jobs.

### Daily Automation Workflow
1. Observers produce raw local JSON output under ignored `data/*-.../` folders.
2. Daily aggregation writes canonical outputs to `data/daily/YYYY-MM-DD/`.
3. Latest snapshots are refreshed in `data/latest/`.
4. PNG significance output is generated from aggregated state.
5. Git commit/push only occurs when there is a real staged change.

### Inspecting Cron Logs
Use the shared log file under the repo to inspect automation health:

```sh
tail -f ~/world-observer/logs/cron.log
```

For scheduler-level issues:

```sh
sudo systemctl status cron
crontab -l
```

## Observers
### Area 51 Reachability
The Area 51 observer uses a bounded airspace aggregation model with 15-minute
UTC buckets and daily Activity Unit (AU) totals:

- `janet_like`: JANET-like transponder movement segments (heuristic class only)
- `other`: non-JANET-like movement segments
- `total`: all movement segments in-bbox

The observer writes daily JSON with rolling 30-day baseline (`mean`, `std`) and
significance (`observed > mean + 2σ` by default). It writes `data/latest/summary.json`
on every run and writes `data/latest/chart.png` only when any AU class is significant.

Privacy constraints are strict: tracked outputs never contain callsigns, tail
numbers, routes, or per-aircraft identifiers.

## Getting Started
Each observer is a self-contained module with a stub `observer.py` file. The
stubs are intentionally conservative and produce placeholder JSON to be replaced
by approved passive data sources in the future.


### Global Reachability Long Horizon
The `global-reachability-long-horizon` observer computes 90-day and 180-day
trend metrics from `global-reachability-score` daily outputs and flags major
long-term events (new 180d highs/lows, mass low events, and trend breaks).

It writes `data/latest/chart.png` only on significant days and removes the PNG
on normal days.

### IPv6 Global Compare
The `ipv6-global-compare` observer derives a daily global IPv6 rate from
`ipv6-locked-states` outputs and compares each country against that baseline.

It computes per-country `delta_vs_global`, 30-day baseline z-scores, and a
trend divergence signal (country flat/down while global rises). It writes
`data/latest/chart.png` only when significance is detected.
