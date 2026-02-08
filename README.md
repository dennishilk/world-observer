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

## Repository Layout
- `observers/`: Passive observer modules emitting JSON.
- `data/`: Raw observation outputs.
- `visualizations/`: Downstream visual analysis (separate from observers).
- `reports/`: Periodic summaries and research notes.
- `scripts/`: Helper scripts for scheduling or data hygiene.
- `cron/`: Example schedules for long-running operation.

## Getting Started
Each observer is a self-contained module with a stub `observer.py` file. The
stubs are intentionally conservative and produce placeholder JSON to be replaced
by approved passive data sources in the future.
