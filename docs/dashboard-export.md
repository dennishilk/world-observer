# Dashboard export pipeline

World Observer keeps observer collection separate from website publishing. The
export layer converts the rolling latest observer snapshots into compact,
stable JSON files that a static dashboard can consume without knowing observer
implementation details.

```text
Observer
  ↓
Latest (`data/latest/*.json`)
  ↓
Dashboard Export (`scripts/export_dashboard.py`)
  ↓
Website (`dashboard/*.json`)
```

## Inputs

The exporter reads JSON snapshots from `data/latest/`. These files are produced
by the existing daily runner and retain each observer's native schema.

The exporter does not run observers, modify observer outputs, or change
`run_daily.py` behavior.

## Outputs

The exporter writes the following compact JSON files to `dashboard/`:

- `summary.json` — dashboard metadata, observer health counts, category counts,
  and dashboard schema version.
- `internet.json` — compact summaries from Internet observers.
- `media.json` — website-safe media fields only.
- `society.json` — empty placeholder for future website sections.
- `environment.json` — empty placeholder for future website sections.

These files are intended to be copied directly into the GitHub Pages repository.
The website should consume only `dashboard/*.json` and should not depend on raw
observer schemas.

## Error handling

Exports are best-effort. If an observer file is missing or invalid, the exporter
records the missing/degraded counts in `summary.json` and still writes all
available dashboard files.

## Usage

```sh
python scripts/export_dashboard.py
```

For tests or local experiments, custom paths can be supplied:

```sh
python scripts/export_dashboard.py --latest-dir /tmp/latest --dashboard-dir /tmp/dashboard
```
