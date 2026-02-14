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

Daily observer execution time is **02:00 UTC** and considered contractual.

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
Canonical daily observers executed by `scripts/run_daily.py`:

- `area51-reachability`
- `asn-visibility-by-country`
- `cuba-internet-weather`
- `dns-time-to-answer-index`
- `dns-tta-stress-index`
- `global-reachability-long-horizon`
- `global-reachability-score`
- `internet-shrinkage-index`
- `ipv6-adoption-locked-states`
- `ipv6-global-compare`
- `ipv6-locked-states`
- `iran-dns-behavior`
- `mx-presence-by-country`
- `mx-presence-per-country`
- `north-korea-connectivity`
- `silent-countries-list`
- `tls-fingerprint-change`
- `traceroute-to-nowhere`
- `undersea-cable-dependency`
- `undersea-cable-dependency-map`

`world-observer-meta` is intentionally excluded from the daily observer list and
is executed separately to generate `summary.json` and `summary.md`.

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

## Fresh Clone and Merge-Resilient Workflow
1. Clone as the observer user and switch to the repository directory.
2. Run setup as root:
   ```sh
   sudo ./setup_world_observer.sh
   ```
3. Setup auto-configures:
   - `origin` to SSH (when currently GitHub HTTPS),
   - repository-local `core.sshCommand` with the deploy key,
   - idempotent cron jobs that always execute inside `.venv`.
4. Re-run setup after merges/pulls to safely re-apply system dependencies and cron entries.

## Deploy Key Setup (GitHub)
1. Generate a key (or let setup generate it):
   ```sh
   ssh-keygen -t ed25519 -f ~/.ssh/id_ed25519_world_observer -C "world-observer-deploy-key"
   ```
2. Add the **public** key to GitHub repo **Deploy keys** with **Allow write access**.
3. Confirm non-interactive SSH auth:
   ```sh
   ssh -o BatchMode=yes -T git@github.com
   ```
4. Confirm git is SSH-only:
   ```sh
   git remote -v
   git config --local --get core.sshCommand
   ```

## Cron Schedule Contract
Installed by `setup_world_observer.sh`:
- Hourly heartbeat (minute `0`): `scripts/heartbeat_push.py`
- Daily run (UTC `02:00`): `scripts/run_daily.py`, `visualizations/generate_significance_png.py`, then `scripts/git_publish.sh`
- Shared logs: `logs/cron.log`

Example validation:
```sh
crontab -l
 tail -n 100 logs/cron.log
```

## High-Level Verification Script
Run repository-level checks with:
```sh
python scripts/verify_repository_health.py
```
Optional push-path validation:
```sh
python scripts/verify_repository_health.py --check-push
```

Checks performed:
- heartbeat execution (idempotent commit behavior, optional push),
- daily runner output generation for all configured observers,
- daily JSON presence + minimal schema contract checks,
- restricted identifier-key scan (IP/domain/cert/raw-route style keys),
- significance behavior simulation (`tls-fingerprint-change`) including PNG creation on forced significance.

## Manual Recovery Steps
- If cron appears idle: check `systemctl status cron`, `crontab -l`, and `logs/cron.log`.
- If push fails: verify deploy key in GitHub and local `core.sshCommand`.
- If observer output is missing: run `python scripts/run_daily.py --date YYYY-MM-DD` manually and inspect stderr in generated error JSON.
- If PNG behavior is unexpected: run the high-level verification script and inspect `data/latest/chart.png` lifecycle.

## Python Environment and Dependencies
- Python runtime is pinned via `.python-version` (`3.12.12`).
- Create and activate venv:
  ```sh
  python3 -m venv .venv
  . .venv/bin/activate
  ```
- Install dependencies:
  ```sh
  pip install -r requirements.txt
  ```
