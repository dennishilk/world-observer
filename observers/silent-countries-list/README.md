# silent-countries-list

## Purpose
This observer identifies countries that appear **silent** across a minimal set of
basic network signals gathered during a single run. It is intentionally limited
in scope and does not attempt to explain why responses are absent.

## What "silence" means here
A country is marked as **silent** when **none** of the following checks succeed
for **any** of its configured targets during the run:

- ICMP ping (single attempt)
- TCP handshake on port 443 (single attempt)
- DNS A record lookup (single attempt)

The observer aggregates only country-level outcomes and does **not** store
per-target details in its output.

## What "silence" does NOT imply
Silence in this context does **not** prove censorship, outages, policy choices,
or intent. Non-response can result from filtering, routing issues, transient
network failures, target downtime, or measurement limitations.

## Limitations and uncertainty
- Single-attempt measurements increase false negatives.
- ICMP may be blocked or require privileges on the measurement host.
- DNS results depend on the resolver configuration of the host running the
  observer.
- Targets may not be representative of a country as a whole.

## Ethical boundaries
- No automated or repeated probing beyond one attempt per signal.
- No inference about cause or attribution.
- No scanning outside the explicit targets list.
- No collection of content or payload data.

## Configuration
Targets are defined in `targets.json` as a list of country entries:

```json
[
  {
    "country": "XX",
    "targets": [
      { "name": "...", "host": "hostname_or_ip" }
    ]
  }
]
```

Provide a list of country entries to match your research needs.
