# traceroute-to-nowhere

## Purpose
This observer measures how far packets travel before paths stop responding. It uses
traceroute cautiously to summarize **where** paths tend to break without attempting to
map or enumerate infrastructure.

## Why traceroute (used cautiously)
Traceroute reveals hop-by-hop responses, but this module intentionally restricts the
measurement to a low TTL and a single probe per hop. The goal is to understand *how far*
traffic travels rather than *which* devices are involved.

## What is intentionally NOT collected
To avoid infrastructure mapping, the observer does **not** store:
- IP addresses
- Hostnames
- Full hop lists
- ASNs
- Geolocation of individual hops

Only coarse summaries are saved, such as the number of hops reached and the termination
reason.

## Why stop points matter more than routes
Stop points indicate where connectivity stalls or is filtered. These patterns can help
identify broad connectivity constraints without collecting sensitive routing details.

## Ethical and legal constraints
- No automation or scheduled runs.
- One traceroute per target per run.
- Conservative probing defaults with strict rate limiting.
- Neutral, scientific reporting focused on aggregate behavior.
- The observer must comply with local laws, acceptable use policies, and operational
  guidelines for measurement ethics.

## Configuration
Targets are defined in `targets.json` with entries:

```json
{ "name": "...", "host": "hostname_or_ip" }
```

## Output
The observer emits JSON with the following schema:

```json
{
  "observer": "traceroute-to-nowhere",
  "timestamp": "ISO8601",
  "targets": [
    {
      "name": "...",
      "host": "...",
      "hops_reached": 0,
      "termination": "completed|timeout|unreachable|filtered",
      "stop_zone": "local|regional|international|transit|unknown",
      "error": null
    }
  ],
  "notes": "..."
}
```
