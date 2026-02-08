# internet-shrinkage-index

## Purpose
The internet-shrinkage-index is a simple, repeatable measure of how much of the
public internet appears reachable at a given point in time. It samples a fixed
set of globally distributed, well-known hosts and records whether those targets
can be reached using a small set of basic network checks.

## What the index represents
The index is the fraction of targets that meet the reachability rule at the time
of measurement. A target is considered reachable when at least two of three
checks succeed:

1. ICMP ping
2. TCP handshake on port 443
3. DNS A record lookup

## What the index does NOT explain
This observer does not diagnose causes. It does not attribute failures to
routing issues, filtering, server outages, or policy changes. It only reports
whether the reachability checks succeeded for each target at the measurement
moment.

## Why consistency matters more than precision
The value of the index comes from running the same checks against the same
targets over time. Absolute precision is less important than consistency because
trends are most meaningful when the measurement method stays stable.

## Limitations
- Targets may themselves be down or rate-limiting, which can lower the index.
- ICMP and TCP reachability can be blocked even when a site is otherwise
  available via alternative paths or protocols.
- DNS resolution depends on local resolver behavior and caching.
- The index reflects a single vantage point and does not represent global
  reachability for every network.

## Output
The observer emits JSON with the following schema:

```json
{
  "observer": "internet-shrinkage-index",
  "timestamp": "ISO8601",
  "total_targets": 0,
  "reachable_targets": 0,
  "index": 0,
  "targets": [
    {
      "host": "...",
      "reachable": false,
      "checks": {
        "ping": false,
        "tcp_443": false,
        "dns": false
      }
    }
  ],
  "notes": "..."
}
```
