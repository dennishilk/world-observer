# internet-shrinkage-index

## Purpose
`internet-shrinkage-index` (ISI) is a passive, trend-based observer that estimates
persistent structural internet contraction over time. It does **not** perform new
network measurements, probing, scanning, or host-level checks.

Instead, it aggregates already-produced daily outputs from:

- `global-reachability-score`
- `asn-visibility-by-country`
- `ipv6-locked-states` (or `ipv6-adoption-locked-states` if available)
- `silent-countries-list` (optional modifier)

## Shrinkage vs outages
ISI is designed to capture **structural shrinkage trends**, not short-lived outages.
Single-day drops may happen for benign reasons; ISI prioritizes persistence,
trend slope, and distance from healthier recent states.

## Country-level score
For each country/day, ISI computes `shrinkage_score` in `[0..1]` using available
signals only (missing signals remain neutral and do not force extreme values):

1. **Trend** over a rolling window (default 30 days):
   - Compute slope on aggregated per-country badness series.
   - Positive badness slope maps to higher shrinkage component.
2. **Distance to recent peak state** (default 90 days):
   - Current badness minus recent minimum badness (normalized to `[0..1]`).
3. **Persistence** (default 30 days):
   - Fraction of day-over-day deltas indicating worsening badness.
4. **Silence modifier** (optional):
   - Raises score conservatively when `silent`/`persistently_silent` signals are present.

### Default weights
- Trend: `0.45`
- Distance-to-peak: `0.35`
- Persistence: `0.20`
- Silence modifier (additive): `0.10`

When primary components are missing, weights are renormalized across available
components. This keeps missing inputs neutral.

## Global index
`global_shrinkage_index` is the equal-weight mean of current country
`shrinkage_score` values.

## Baselines and significance
Baselines use a rolling 30-day history (country and global):

- `baseline_30d.mean`
- `baseline_30d.std`
- `delta = current - baseline_mean`

A run is significant when any trigger fires:

- Country reaches a new local maximum shrinkage score
- Global index reaches a new maximum
- Mass event: at least `K` countries hit new maxima (default `K=5`)
- Trend regime change in global slope magnitude

## PNG policy (strict and rare)
`data/latest/chart.png` is generated **only** when significance is true.

- Path is fixed: `data/latest/chart.png`
- File is overwritten on significant events
- No PNG is produced on normal days (existing chart is removed)

The chart includes:

- Global index over recent days
- Countries hitting new maxima
- Trigger annotation

## Outputs
### Daily observer JSON
Written by runner to:

- `data/daily/YYYY-MM-DD/internet-shrinkage-index.json`

Schema:

```json
{
  "observer": "internet-shrinkage-index",
  "date_utc": "YYYY-MM-DD",
  "data_status": "ok|partial|unavailable",
  "countries": [
    {
      "country": "US",
      "shrinkage_score": 0.123,
      "components": {
        "trend": 0.11,
        "distance_to_peak": 0.2,
        "persistence": 0.4,
        "silence_modifier": null
      },
      "baseline_30d": {"mean": 0.09, "std": 0.03},
      "delta": 0.033,
      "is_new_max": false
    }
  ],
  "global": {
    "global_shrinkage_index": 0.1,
    "baseline_30d": {"mean": 0.08, "std": 0.02},
    "is_new_max": false
  },
  "summary_stats": {
    "countries_evaluated": 1,
    "new_max_count": 0,
    "mass_event": false
  },
  "significance": {
    "any_significant": false,
    "triggers": []
  }
}
```

### Latest summary JSON
Observer-maintained:

- `data/latest/summary.json`

Includes:

- `last_run_utc`
- `latest_date_utc`
- `last_7_days` (`new_max_count`, `mass_event`)
- `chart_path` only when chart exists

## Runtime notes
The observer is cron-safe and unattended. It only reads local daily JSON files,
then emits JSON to stdout for `scripts/run_daily.py` to store.
