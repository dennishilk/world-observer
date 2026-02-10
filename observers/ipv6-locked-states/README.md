# ipv6-locked-states

## Purpose
This observer tracks APNIC Labs country-level IPv6 capability metrics for a
configurable `locked_states` seed list.

Default seed countries include:
- KP (North Korea)
- IR (Iran)
- CU (Cuba)

The selection is config-driven and can be extended. As a policy framework,
maintainers can map seed choices to Freedom House *Freedom on the Net*
assessments.

## Data source and privacy constraints
- Uses only aggregated APNIC Labs country measurements.
- No probing/scanning is performed.
- No IP addresses, prefixes, or ASNs are stored.

## Metrics
Per country/day output:
- `ipv6_capable_rate` normalized to `0..1`
- `sample_size` when APNIC provides one
- `data_status` (`ok`, `partial`, `unavailable`)

## Baseline and significance
For each country:
- Rolling `baseline_30d` (`mean`, `std`) from prior daily observer outputs.
- `delta_pp` = (observed - baseline mean) in percentage points.
- `z` = standardized change (safe when std = 0).

A country is significant when either condition is true:
- `abs(z) > sigma_mult` (default `2.0`)
- `abs(delta_pp) >= step_threshold_pp` (default `5.0`)

A mass event is triggered when significant countries in one day are at least
`mass_event_k` (default `3`).

## PNG policy (rare chart)
`data/latest/chart.png` is created **only** when `any_significant` is true
(and therefore also on mass events), and overwritten on each such event.
No chart file is kept on normal days.

The PNG includes simple bars comparing observed vs baseline mean for top
significant countries, and trigger reasons embedded in PNG metadata.

## Outputs
- Daily: `data/daily/YYYY-MM-DD/ipv6-locked-states.json`
- Latest summary: `data/latest/summary.json`
- Rare chart: `data/latest/chart.png` (significant days only)
