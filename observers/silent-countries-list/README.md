# silent-countries-list

## Purpose
`silent-countries-list` is a **correlation-only meta-observer**. It does not probe
networks, does not scan, and does not call external services. It consumes daily
JSON outputs already produced by other observers and computes a country-level
"Silence Score" to identify persistent or emerging silence patterns.

## Inputs
The observer reads available daily JSON files for the configured date from:

- `data/daily/YYYY-MM-DD/<observer>.json`

Default contributing observers (configurable):

- `north-korea-connectivity`
- `iran-dns-behavior`
- `cuba-internet-weather`
- `internet-shrinkage-index`
- `global-reachability-score`
- `ipv6-adoption-locked-states`

Missing inputs are handled gracefully. `data_status` is:

- `ok` when all configured sources are present
- `partial` when some are missing
- `unavailable` when no usable source data exists

## Silence Score (0.0 to 1.0)
Daily score is a weighted sum of normalized signal components.

Configured default weights (`config.json`):

- `hard_silence` (0.55): strong indication from explicit silent/dark states
- `low_reachability` (0.20): low country reachability percentage
- `dns_anomaly` (0.15): DNS failures / non-answer dominated outcomes
- `time_to_silence` (0.05): reserved for observers providing this signal
- `ipv6_absence` (0.05): weak/moderate contribution when IPv6 is absent

Weights are normalized at runtime, then clipped to `[0, 1]` total score.

## Daily classification
Each country/day gets one class:

- `normal`
- `degrading`
- `silent`
- `persistently_silent`
- `recovering`
- `anomalous`

Decision guidance:

- `persistently_silent` requires score >= persistent threshold for N consecutive
  days (default N=3).
- `recovering` is assigned when day-over-day delta is sufficiently negative
  (default <= -0.10).
- `anomalous` captures sudden absolute jumps/drops (default >= 0.35).

## Baseline and significance
For each country, the observer builds a rolling 30-day baseline from prior
`silent-countries-list.json` outputs:

- mean
- standard deviation
- z-score for current day

Significance triggers (default sigma=2.0):

- country z-score > sigma threshold
- class transition into `silent` or `persistently_silent`
- newly appearing country in Top-N silent list
- mass event: more than K class changes in one day

## PNG generation rules
`data/latest/chart.png` is generated **only** when `any_significant == true`.

- No daily PNG output.
- Single latest chart path only.
- Chart contains Top-N scores, highlights changed/new entries, and lists trigger
  reasons.

## Outputs
Tracked outputs produced by this observer:

- `data/daily/YYYY-MM-DD/silent-countries-list.json`
- `data/latest/summary.json`
- `data/latest/chart.png` (significance-only)

No IPs, hostnames, ASNs, routes, operator identities, or target identifiers are
stored in observer output.
