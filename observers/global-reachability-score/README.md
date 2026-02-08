# global-reachability-score

## Purpose
This observer computes a simple, transparent reachability score for selected
countries using three basic network signals per target:

- ICMP ping (success/failure)
- TCP handshake on port 443 (success/failure)
- DNS A record lookup (answer/failure)

It aggregates those signals into a single country-level score without storing
per-target details.

## Scoring model
Each target can earn up to **3 points** (one per signal). The country-level
score is computed as:

```
score_percent = (score / max_score) * 100
```

Where:

- `score` = total successful checks across all targets.
- `max_score` = `targets_tested * 3`.

The output includes `score`, `max_score`, and `score_percent` for transparency.

## What the score represents
- A lightweight snapshot of basic reachability for a country’s selected targets.
- Whether simple connectivity signals succeed at the moment of measurement.

## What the score does NOT represent
- It does **not** diagnose causes of failures (routing, filtering, outages, etc.).
- It does **not** measure performance, bandwidth, or latency quality.
- It does **not** claim comprehensive national reachability.

## Limitations
- Results depend on the small, explicit target list in `targets.json`.
- ICMP may be blocked or require elevated permissions on the probing host.
- DNS results can vary by resolver location and caching.
- Single-attempt checks can miss intermittent connectivity.

## Ethical boundaries
- Measurements are minimal and limited to explicit targets.
- No retries beyond a single attempt per signal.
- No automated escalation, scanning, or probing beyond the defined checks.
- This observer is intended for research transparency, not operational diagnosis.

## Configuration
Targets are defined in `targets.json`:

```json
{
  "country": "XX",
  "targets": [
    {"name": "Example", "host": "example.com"}
  ]
}
```
