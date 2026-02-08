# dns-time-to-answer-index

## Purpose
DNS response time is a useful signal of network stress and filtering because it captures
how quickly resolvers can answer basic queries without inspecting content or tracing
routes. Slower responses can indicate congestion, resolver overload, or interference,
while still preserving user privacy by avoiding payload inspection.

## What this index measures
- Sequential DNS **A** and **AAAA** lookup latency (milliseconds).
- Response status (success, timeout, NXDOMAIN, etc.).

## What this index does **not** represent
- It does **not** evaluate website availability, HTTP performance, or content filtering.
- It does **not** record DNS answers, IP addresses, resolver identities, or TTL values.
- It does **not** infer routing paths or network topology.

## Methodology
- Targets are defined in `targets.json` with `{ "name": "...", "domain": "..." }` entries.
- Each target is queried sequentially with a conservative timeout (3 seconds).
- No retries beyond the single attempt per record type.

## Output schema
The observer emits JSON with the following structure:

```json
{
  "observer": "dns-time-to-answer-index",
  "timestamp": "ISO8601",
  "targets": [
    {
      "name": "...",
      "domain": "...",
      "queries": {
        "A": {
          "status": "...",
          "query_ms": 0,
          "error": null
        },
        "AAAA": {
          "status": "...",
          "query_ms": 0,
          "error": null
        }
      }
    }
  ],
  "summary": {
    "total_queries": 0,
    "successful": 0,
    "timeouts": 0,
    "avg_query_ms": 0
  },
  "notes": "..."
}
```

## Limitations
- DNS latency is an indirect signal; it can be affected by local resolver load,
  upstream connectivity, or regional congestion.
- Results can vary based on the local resolver configuration and cache state.
- Timeouts and NXDOMAIN responses are recorded but not interpreted as censorship.

## Ethical boundaries
- Only basic DNS timing is collected.
- No content, resolver identities, or answers are stored.
- Use this observer only for aggregate, high-level network health insights.

## Dependencies
- `dnspython` (install with `pip install dnspython`).
