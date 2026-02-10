# global-reachability-long-horizon

## Purpose
Computes long-horizon (90d/180d) trend metrics using only historical
`global-reachability-score` daily JSON outputs.

## Inputs
- `data/daily/YYYY-MM-DD/global-reachability-score.json`

## Outputs
- `data/daily/YYYY-MM-DD/global-reachability-long-horizon.json`
- `data/latest/summary.json`
- `data/latest/chart.png` (only when significance is true)

## Significance triggers
- New global 180d low/high
- Mass event: country new-180d-lows count >= `mass_event_k`
- Global trend break: 180d slope delta exceeds `trend_break_threshold`

## Safety model
This observer does not perform probing, scanning, or network access.
It only reads existing daily JSON outputs and writes aggregated analytics.
