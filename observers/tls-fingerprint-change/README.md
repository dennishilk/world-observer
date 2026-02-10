# tls-fingerprint-change

## Purpose
This observer detects **significant, country-level TLS handshake behavior changes** using only aggregated metrics.

It intentionally does **not** collect or publish stable TLS fingerprints (JA3/JA3S), certificates, hostnames, domains, or IP addresses in tracked outputs.

## Privacy constraints
The observer enforces privacy by design:

- Probes use a small, static neutral target set.
- Per-connection handshake details are written only to local state (`state/tls-fingerprint-change/`) for troubleshooting and are gitignored.
- Tracked JSON output contains only per-country aggregates:
  - `tls_success_rate`
  - `handshake_abort_rate`
  - `tls_version_distribution`
  - `cipher_class_distribution`
  - `alpn_presence_rate`
  - `sample_size`
  - `data_completeness`

## Change score method
`tls_change_score` is normalized to `[0, 1]` and combines:

- Version distribution delta (L1 distance / 2)
- Cipher class distribution delta (L1 distance / 2)
- Positive abort-rate increase vs baseline
- Absolute ALPN presence-rate delta

Default weights:

- `version_delta`: 0.40
- `cipher_delta`: 0.25
- `abort_delta`: 0.20
- `alpn_delta`: 0.15

Each country compares against its rolling 30-day baseline.

## Significance
A country is significant if any condition is true:

- `z(tls_change_score) > sigma_mult` (default `2.0`, with minimum history days)
- TLS major version shift (TLS1.3 share shift above threshold)
- Abort-rate jump component above safety threshold

A mass event is flagged when significant countries on a day are `>= mass_event_k` (default `5`).

## PNG rule
The observer generates `data/latest/chart.png` **only when `any_significant == true`**.
If not significant, the chart is removed.

The PNG includes:

- Top countries by `tls_change_score`
- Simplified before/after bars (`baseline mean` vs `current score`)
- Trigger annotations in PNG metadata

## Runtime controls
- `WORLD_OBSERVER_DATE_UTC=YYYY-MM-DD` overrides run date.
- `WORLD_OBSERVER_TLS_FORCE_SIGNIFICANT=1` forces significance for test verification of PNG path behavior.

## Output files
- Daily: `data/daily/YYYY-MM-DD/tls-fingerprint-change.json`
- Latest summary: `data/latest/summary.json`
- Significant days only: `data/latest/chart.png`
