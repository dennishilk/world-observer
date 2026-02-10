# dns-tta-stress-index

## Purpose
`dns-tta-stress-index` tracks **daily DNS answer-time stress** using only
aggregated outcomes. It measures time-to-answer (TTA) behavior for A/AAAA
queries and converts those aggregates into a normalized stress score per
country cohort.

## Privacy and safety constraints
This observer is explicitly constrained to avoid sensitive telemetry in tracked
outputs:

- No IP addresses.
- No hostnames in tracked JSON.
- No resolver identifiers.
- No per-query artifacts in tracked JSON.

Raw per-query samples are written only to local state under
`state/dns-tta-stress-index/` for troubleshooting and are gitignored.

## Metrics (daily, per country)
- `tta_mean_ms`
- `tta_p95_ms`
- `timeout_rate`
- `success_rate`
- `jitter_ms`
- `probe_count`
- `data_completeness`

## Stress score
`dns_stress_score` is normalized to `[0, 1]` from weighted components:

- Elevated `tta_p95_ms`
- Increased `timeout_rate`
- Decreased `success_rate`
- Increased `jitter_ms`

Weights are configurable in `config.json` (`weights`). Missing or partial data
is completeness-weighted so incomplete days do not automatically become `1.0`.

## Baseline and significance
For each country, a rolling 30-day baseline is computed from historical
`dns_stress_score` values.

Significant if any trigger matches:
1. `z-score > sigma_mult` (default `2.0`)
2. `timeout_rate > hard_timeout_rate`
3. Mass event: significant countries `>= mass_event_k` (default `5`)

## PNG policy (intentionally rare)
`data/latest/chart.png` is generated **only** when
`significance.any_significant == true`.

On non-significant days no PNG is retained.

## Tracked outputs
- `data/daily/YYYY-MM-DD/dns-tta-stress-index.json`
- `data/latest/summary.json`
- `data/latest/chart.png` (significant days only)
