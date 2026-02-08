# asn-visibility-by-country

## Purpose
This observer measures, at a high level, how many autonomous systems (ASNs)
from a given country appear publicly reachable. ASNs are the administrative
identities that operate Internet routing domains (for example, a major ISP or
cloud provider). Visibility matters because if ASNs in a country are not
reachable, it can indicate broad outages, filtering, or infrastructure issues.

This module is **not** BGP analysis. It does not inspect routing tables,
announcement paths, or any changes in routing behavior. It only performs a
single minimal reachability check per ASN.

## Data sources
Input comes from a static `asn_sources.json` file containing a country code and
representative probe IPs per ASN. This file is expected to be populated from
public ASN-to-country mappings and manually chosen representative IPs.

## How it works
For each ASN listed in `asn_sources.json`, the observer performs **one** TCP 443
connectivity check to the representative IP. It records only whether the probe
is reachable (`true`/`false`). There are no retries, no scanning, and no storage
of IP ranges or prefixes.

## Output
The observer emits JSON:

```json
{
  "observer": "asn-visibility-by-country",
  "timestamp": "ISO8601",
  "countries": [
    {
      "country": "XX",
      "total_asns": 1,
      "visible_asns": 1,
      "visibility_ratio": 1.0
    }
  ],
  "notes": "..."
}
```

## Limitations
- Single probe IPs are not representative of full ASN reachability.
- TCP 443 reachability does not imply service availability.
- Results depend on the accuracy and freshness of the ASN-to-country mapping.
- This is a minimal, passive signal; it does not infer routing behavior.

## Ethical boundaries
- No scanning or automation.
- No retries beyond one probe per ASN.
- No storage of prefixes, IP ranges, or routing paths.
- No BGP analysis or routing change monitoring.
