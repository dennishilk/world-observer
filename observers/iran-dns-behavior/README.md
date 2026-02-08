# iran-dns-behavior

## Purpose
This observer measures how DNS responses behave for selected targets when queried
normally. DNS behavior provides a direct signal about reachability, filtering,
and resolver behavior without attempting to bypass any controls. Recording
response status and timing helps distinguish silence, refusal, and ordinary
answers in a neutral, repeatable way.

## Why DNS behavior matters
DNS is often the first place where access is interrupted. By comparing outcomes
such as answers, timeouts (silence), and explicit refusals, researchers can
separate likely blocking behaviors from ordinary resolution failures. False
answers (responses that do not match expected content) can also indicate
interference, so this observer tracks only whether an answer exists and how
many records were returned, without storing any record data.

## What is (and is not) measured
- **Measured**: response status, query time in milliseconds, and the count of
  answers returned for A, AAAA, MX, and TXT queries.
- **Not stored**: record contents, IP addresses, TXT payloads, routing data, or
  any traceroute information.

## Ethics and legal boundaries
This observer is strictly observational and **does not attempt to circumvent
censorship**. It issues standard DNS queries using the system resolver with a
small fixed retry count and records only coarse outcomes. Operators must ensure
that targets are appropriate for their jurisdiction and that data collection
respects local laws and ethical research norms.

## Data sources
Targets are defined in `targets.json` as a short list (4–8 entries) of domains.
Each target is queried independently.

## Dependencies
This observer uses `dnspython` for DNS resolution. Install it alongside the
project requirements if it is not already available.

## Output
The observer emits JSON with the following schema:

```json
{
  "observer": "iran-dns-behavior",
  "timestamp": "ISO8601",
  "targets": [
    {
      "name": "...",
      "domain": "...",
      "queries": {
        "A": {
          "status": "...",
          "query_ms": 0,
          "answer_count": 0,
          "error": null
        }
      }
    }
  ],
  "summary": {
    "total_queries": 0,
    "answered": 0,
    "timeouts": 0,
    "refused": 0
  },
  "notes": "..."
}
```
