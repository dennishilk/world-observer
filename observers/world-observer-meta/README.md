# world-observer-meta

## Purpose
The **world-observer-meta** module aggregates daily JSON outputs from other
observer modules into a single, neutral summary for the same date. It performs
**no network measurements** and does not recompute metrics; it only collects
high-level fields already reported by other observers.

## What it aggregates
- JSON artifacts produced by other observers for a given date.
- High-level fields only (for example: index values, scores, flags) when they
  already exist in the source outputs.
- A list of observers that produced output versus those missing output for the
  date.

## What it does **not** do
- **No active measurement** or probing of any kind.
- **No recomputation** or derivation of metrics beyond reading existing values.
- **No inference** about causes, intent, or interpretation of results.
- **No modification** of original observer output files.

## Outputs
The meta observer writes its summary into the daily directory:
`data/daily/YYYY-MM-DD/`

- `summary.json`: structured, neutral aggregation.
- `summary.md`: optional, minimal human-readable summary.

### summary.json schema (example)
```json
{
  "observer": "world-observer-meta",
  "date": "YYYY-MM-DD",
  "observers_run": ["area51-reachability"],
  "observers_missing": ["tls-fingerprint-change-watcher"],
  "highlights": {
    "internet_shrinkage_index": 0.98,
    "global_reachability_score": null,
    "silent_countries_count": null
  },
  "notes": "Missing observers: ..."
}
```

## Limitations
- If observer outputs are missing or malformed, the summary still completes and
  records the issue in the notes.
- Highlight fields are `null` when the source data does not report them.
- Interpretation is intentionally left to humans to avoid overreach.

## Usage
The module exposes `run(date=None)`:
- `date=None` uses the current UTC date.
- `date="YYYY-MM-DD"` aggregates that specific day.

The module is intentionally minimal and defensive by design.
