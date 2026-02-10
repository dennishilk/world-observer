# north-korea-connectivity

## Purpose
This observer is a **stateful, multi-layer connectivity monitor** focused on
aggregated behavior, not binary up/down status. It emits one daily JSON record,
builds a 30-day rolling baseline, and only writes a PNG when change is
statistically significant.

## Measurement model (aggregated only)
The observer probes a constrained target list and stores **only daily aggregate
metrics**:

- DNS: response existence + mean latency.
- TCP: connect outcomes over ports 80/443/22.
- ICMP: reachability outcomes.
- TLS: handshake success/failure over port 443.

For each layer, the output includes:

- `success_rate`
- `probe_count`
- `data_completeness`
- `mean_latency_ms` (DNS only)

No target names, hostnames, IP addresses, routes, ASNs, certificates,
fingerprints, or per-probe identifiers are written to tracked outputs.

## Daily connectivity states
A single state is derived per day:

- `silent`: no layer responds.
- `dark`: DNS responds but TCP/TLS fail.
- `partial`: limited TCP/TLS success.
- `controlled`: stable/narrow TCP+TLS success pattern.
- `anomalous`: statistically unusual increase/deviation from baseline.
- `open_ish`: significantly broader reachability than baseline.

## Time-to-silence index
The observer runs multiple bounded trials and measures elapsed time until all
layers in a trial become silent. It reports:

- `mean_seconds`
- `p95_seconds`
- `worst_seconds`

## Baseline and significance
A 30-day rolling baseline is computed for layer success rates and
`time_to_silence` metrics (`mean/stddev`).

Significance is true if either:

1. A metric exceeds the sigma threshold (`sigma_mult`, default `2.0`).
2. A rare state transition is observed versus recent state history.

## PNG policy (intentionally rare)
`data/latest/chart.png` is generated **only** when
`significance.any_significant == true`.

This intentionally keeps chart events sparse in Git history and avoids noisy,
daily visual artifacts. On normal days, no new PNG is generated.

## Outputs
Tracked outputs for this observer:

- `data/daily/YYYY-MM-DD/north-korea-connectivity.json`
- `data/latest/summary.json`
- `data/latest/chart.png` (significant events only)
