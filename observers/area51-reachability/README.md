# area51-reachability

## Scope
This observer tracks **aggregated airspace activity units (AU)** in a configurable Area 51 region bounding box.

It does **not** identify flights, aircraft, routes, callsigns, or individuals in tracked outputs.

## Measurement model
- UTC day divided into `15` minute buckets (configurable).
- For each bucket:
  - `au_total`: moving transponder segments in the bbox.
  - `au_janet_like`: subset matching JANET-like kinematic activity class (speed/altitude/heading/time-window patterns only).
  - `au_other`: `au_total - au_janet_like`.
- Daily totals are sums over available buckets.

## Privacy and safety boundaries
- Classification uses only anonymous numeric movement properties (e.g., speed, altitude, heading, bucket time).
- Callsigns, ICAO hex addresses, tail numbers, aircraft types, and operator identifiers are not accessed for classification (including in-memory pattern checks).
- Raw bucket cache is local state under `state/area51-reachability/` and is not part of tracked output contract.

## Output contract
Daily output (`data/daily/YYYY-MM-DD/area51-reachability.json`):
- `observer`, `date_utc`, `data_status`, `bucket_minutes`, `bbox`, `bucket_count`
- `au.{janet_like,other,total}`
- `baseline_30d` with `mean` and `std` for each class
- `significance` with `sigma_mult`, per-class significance + z-score, and `any_significant`

Latest output (`data/latest/summary.json`):
- `last_run_utc`, `latest_date_utc`
- `last_7_days` mini summary
- `chart_path` (set only when significance chart exists)

## Significance
Default threshold is `observed > mean + (2.0 * stddev)` using rolling 30-day baseline for each AU class.

## Chart behavior
`data/latest/chart.png` is generated only if `significance.any_significant == true`.
