# ipv6-global-compare

## Purpose
This observer compares each country's IPv6 adoption against the same-day global
IPv6 trend derived from `ipv6-locked-states` daily JSON outputs.

It detects:
- structural divergence (`delta_vs_global` shifts away from baseline),
- trend divergence (country flat/down while global rises),
- broad synchronized events (`mass_event`).

## Inputs and constraints
- Reads only existing files in `data/daily/YYYY-MM-DD/ipv6-locked-states.json`.
- Performs no probing, scanning, or network access.
- Uses one observer input source at a time (`ipv6-locked-states`).

## Metrics
Per country/day:
- `ipv6_rate`: today's country value from source observer.
- `global_ipv6_rate`: arithmetic mean of all available country rates for day.
- `delta_vs_global`: `ipv6_rate - global_ipv6_rate`.
- `trend_delta`: country slope minus global slope over rolling trend window.
- `baseline_30d`: mean/std of prior `delta_vs_global` values (30d default).
- `z`: standardized `delta_vs_global` shift vs baseline.
- `is_significant`: true when z-threshold or trend-divergence trigger fires.

## Baseline and significance
A country is significant when either is true:
- `abs(z) > sigma_mult` (default `2.0`)
- trend divergence: country slope `<= divergence_max_country_slope` while
  global slope `>= divergence_min_global_slope`

Mass event: `significant_count >= mass_event_k` (default `3`).

## PNG policy (strict)
`data/latest/chart.png` is generated only when `any_significant == true`.

On significant days, chart contains:
- strongest country divergences,
- global IPv6 trend line,
- short trigger annotation in PNG metadata.

On normal days, no PNG is kept.

## Outputs
- Daily: `data/daily/YYYY-MM-DD/ipv6-global-compare.json`
- Latest summary: `data/latest/summary.json`
- Significant-only chart: `data/latest/chart.png`
