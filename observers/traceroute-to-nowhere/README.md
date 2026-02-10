# traceroute-to-nowhere

## Purpose
This observer runs a **minimal** daily traceroute set against a small static anchor list and records only aggregated indicators of potential path failure/blackhole behavior.

## Strict privacy model
This observer is intentionally designed to avoid route mapping. It **never** stores or publishes:
- hop IP addresses
- hop hostnames
- ASNs
- exact routes
- per-target route details

Hop-level lines are parsed in-memory only to derive coarse per-trace summaries and then discarded.

## Probe profile
- Small static anchor list (default: 8 targets)
- System `traceroute` with conservative settings:
  - numeric mode (`-n`)
  - single probe per hop (`-q 1`)
  - bounded max TTL (default 16)
  - short timeout (default 1.5s)
- One run per anchor with light pacing between traces

## Aggregated metrics emitted
- `trace_count`
- `fail_rate`
- `median_last_replied_hop`
- `early_blackhole_rate` (`last_replied_hop <= 3`)
- `timeout_hop_density` (mean unanswered hop proportion)

## Significance model
A rolling baseline (default 30 days) is computed for:
- `fail_rate`
- `median_last_replied_hop`

A day is marked significant if any trigger fires:
- `z(fail_rate) > sigma_mult` (default 2.0)
- median hop drops past `median_drop_threshold`
- mass event: failed anchors >= half the configured anchors

## Output contract
### Daily file
`data/daily/YYYY-MM-DD/traceroute-to-nowhere.json`

Schema:

```json
{
  "observer": "traceroute-to-nowhere",
  "date_utc": "YYYY-MM-DD",
  "data_status": "ok|partial|unavailable",
  "anchors": {"count": 8},
  "metrics": {
    "trace_count": 8,
    "fail_rate": 0.125,
    "median_last_replied_hop": 7.0,
    "early_blackhole_rate": 0.0,
    "timeout_hop_density": 0.18
  },
  "baseline_30d": {
    "fail_rate": {"mean": 0.09, "std": 0.04},
    "median_last_replied_hop": {"mean": 8.2, "std": 0.8}
  },
  "significance": {
    "sigma_mult": 2.0,
    "any_significant": false,
    "triggers": []
  }
}
```

### Latest summary
`data/latest/summary.json` includes:
- `last_run_utc`
- `latest_date_utc`
- `last_7_days` (`fail_rate` + `any_significant`)
- `chart_path` **only when a chart exists**

### PNG policy (strict)
- PNG is generated **only** when `any_significant == true`
- Path is fixed to: `data/latest/chart.png`
- Existing chart is overwritten on significant events
- No chart is retained on normal days
