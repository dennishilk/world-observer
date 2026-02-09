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
- `data/`: Raw observation outputs.
- `visualizations/`: Downstream visual analysis (separate from observers).
- `reports/`: Periodic summaries and research notes.
- `scripts/`: Helper scripts for scheduling or data hygiene.
- `cron/`: Example schedules for long-running operation.

## Observers
### Area 51 Reachability
The Area 51 observer focuses on mundane, public-facing signals (reachability,
DNS behavior, and coarse traceroute outcomes). It is intentionally constrained
to avoid sensitive data collection and to preserve long-term comparability.

#### Flight Activity (Aggregated, Non-Tracking)
- This project does **not** track individual aircraft, and it performs **no**
  real-time monitoring of flights.
- No routes, identifiers, destinations, timestamps per flight, or aircraft
  metadata are collected or stored.
- Activity is aggregated daily into simple counts and evaluated statistically.
- Significance is based on deviations from a long-term baseline, **not** on
  absolute activity levels or speculative interpretation.

## Getting Started
Each observer is a self-contained module with a stub `observer.py` file. The
stubs are intentionally conservative and produce placeholder JSON to be replaced
by approved passive data sources in the future.
