# ipv6-adoption-locked-states

## Purpose
This observer measures whether IPv6 is **practically usable** for a small set of
selected targets in countries with historically restricted or centralized
networks. “IPv6 adoption” in this module means that **native IPv6 connectivity
works end-to-end** for these targets, not just that IPv6 exists in routing tables.

## What “IPv6 available” means here
A target is counted as IPv6 available only when **both** of the following are true:

1. A DNS AAAA record exists for the hostname.
2. A TCP handshake to port 443 succeeds **over IPv6**.

If either check fails, the target is **not** considered IPv6 available.

## Why native IPv6 matters
Native IPv6 availability indicates that a network can reach modern services
without relying on translation layers. This is especially important in locked or
centralized environments where translation gateways may be policy-controlled or
inconsistently deployed.

## What is intentionally NOT tested
To keep the measurement conservative and non-invasive, this observer does **not**:

- Use IPv6 tunneling mechanisms
- Use NAT64 or other translation layers
- Fall back to IPv4
- Perform traceroute or ping
- Retry more than once per target

## Output
The observer emits JSON with aggregated results per country:

```json
{
  "observer": "ipv6-adoption-locked-states",
  "timestamp": "2024-01-01T00:00:00+00:00",
  "countries": [
    {
      "country": "XX",
      "targets_tested": 2,
      "ipv6_available_targets": 1,
      "ipv6_available": true
    }
  ],
  "notes": "..."
}
```

## Targets
Targets are defined in `targets.json` using the structure:

```json
{
  "country": "XX",
  "targets": [
    { "name": "Example", "host": "example.com" }
  ]
}
```

## Limitations and ethics
- Results are **not** a comprehensive census; they only reflect the small target
  set listed in `targets.json`.
- A single failed handshake does not prove censorship; it can reflect outages,
  routing issues, or server-side configuration.
- The observer performs minimal, low-impact checks and avoids intrusive probing.
