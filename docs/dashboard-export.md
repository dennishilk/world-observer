# Dashboard export pipeline

World Observer keeps observer collection separate from website publishing. The
export layer converts the rolling latest observer snapshots into compact,
stable JSON files and simple history files that a static dashboard can consume
without knowing observer implementation details.

```text
Observer
  ↓
Latest (`data/latest/*.json`)
Daily archive already produced by run_daily (`data/daily/YYYY-MM-DD/*.json`)
  ↓
Dashboard Export (`scripts/export_dashboard.py`)
  ↓
Website (`dashboard/*.json`)
```

## Inputs

The exporter reads JSON snapshots from `data/latest/`. These files are produced
by the existing daily runner and retain each observer's native schema.

For history exports, the exporter also reads only daily outputs that already
exist under `data/daily/YYYY-MM-DD/`. It does not scrape archived websites,
import external archives, or generate historical data that is not already in
the repository's daily output tree.

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
- `history/media-language-germany.json` — compact Germany media-observer time
  series for trend charts.

These files are intended to be copied directly into the GitHub Pages repository.
The website should consume only `dashboard/*.json` and should not depend on raw
observer schemas.

## History export

The first history export is for the Germany media observer. It scans every
available `data/daily/YYYY-MM-DD/media-language-germany.json` file, sorts points
by date, and writes `dashboard/history/media-language-germany.json`.

Each point keeps only website-friendly fields:

- `date`
- `fear_index_overall`
- `public_broadcast`
- `private_media`
- `headline_count`
- up to three `top_terms`

The history file also includes simple 7-day and 30-day windows. Each window
reports its point `count`; when numeric fear-index values are available it also
includes `latest`, `previous`, `delta`, `min`, `max`, and `avg` as applicable.

The history export intentionally does not include diagnostics, full raw observer
JSON, or full headline lists.

This is not a historical backfill. No 1984-era backfill is implemented yet, and
historical archive import remains future work.

## Error handling

Exports are best-effort. If an observer file is missing or invalid, the exporter
records the missing/degraded counts in `summary.json` and still writes all
available dashboard files.

If no daily media files exist, the exporter still writes a valid empty
`dashboard/history/media-language-germany.json` file with no points and window
counts of zero.

## Usage

```sh
python scripts/export_dashboard.py
```

For tests or local experiments, custom paths can be supplied:

```sh
python scripts/export_dashboard.py --latest-dir /tmp/latest --dashboard-dir /tmp/dashboard --daily-dir /tmp/daily
```
