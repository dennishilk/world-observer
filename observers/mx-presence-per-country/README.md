# mx-presence-per-country

## Purpose
Measure **aggregated MX presence and basic reachability** per country from a static, neutral domain sample.

## Privacy and data-handling constraints
- DNS probing is minimal and aggregated.
- Tracked outputs never include domain names, MX hostnames, or IP addresses.
- Per-sample/raw probe details are stored only under `state/mx-presence-per-country/` for local operations and are gitignored.

## Daily metrics (per country)
- `sample_size`
- `mx_present_rate`
- `mx_absent_rate`
- `mx_unreachable_rate`
- `mx_timeout_rate`
- `data_completeness`
- Optional counts: `mx_present_count`, `mx_unreachable_count`

## Baseline and significance
- Rolling baseline window: 30 days by default.
- Baseline fields are computed for:
  - `mx_present_rate` (mean/std)
  - `mx_unreachable_rate` (mean/std)
- Significance triggers:
  - `z(mx_present_rate) < -sigma_mult`
  - `z(mx_unreachable_rate) > sigma_mult`
  - Mass event when `significant_count >= mass_event_k`

## PNG policy (strict)
- A PNG is generated **only** when `any_significant == true`.
- Output path is always: `data/latest/chart.png`.
- PNG is overwritten on each significant event.
- No PNG is kept on normal days.

## Tracked outputs
- `data/daily/YYYY-MM-DD/mx-presence-per-country.json`
- `data/latest/summary.json`
- `data/latest/chart.png` (only when significant)
