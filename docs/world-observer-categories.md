# World Observer Category Architecture Plan

This document describes a future category architecture for World Observer. It is
planning documentation only: it does not require moving observer files, changing
`scripts/run_daily.py`, or refactoring existing observer paths.

## Goals

World Observer currently organizes runnable observers by path under `observers/`.
That layout should remain stable. Future category support should be expressed as
metadata so dashboards, reports, and downstream tooling can group observers
without coupling category meaning to filesystem locations.

The category architecture should:

- keep existing observer paths unchanged;
- avoid changes to daily runner behavior unless a future implementation requires
  metadata discovery;
- make dashboard grouping explicit and durable;
- allow planned observers to be documented before they exist as code;
- preserve observer independence by keeping category metadata descriptive rather
  than operational.

## Proposed top-level categories

### `internet`

Observers about network reachability, DNS behavior, routing visibility, IP
adoption, connectivity, transport fingerprints, and other public internet
infrastructure signals.

### `media`

Observers about public media signals, language usage, information flow, and
other passive measurements of published communication patterns.

### `society`

Observers about public indicators of everyday social infrastructure, cost of
living, transport, postal services, utilities, and other civic or economic
signals.

### `environment`

Observers about public weather, climate, hazard, natural-disaster, and other
environmental signals.

## Future observer metadata

Future observer metadata should include these fields:

| Field | Purpose |
| --- | --- |
| `category` | One of the top-level categories: `internet`, `media`, `society`, or `environment`. |
| `display_name` | Human-readable observer name for dashboards and reports. |
| `description` | Short explanation of the observer's passive signal and intended interpretation. |
| `tags` | List of secondary grouping labels, such as country, signal type, or domain. |
| `dashboard_priority` | Numeric or ordered value used by dashboards to sort important observers first. |

Example metadata shape:

```json
{
  "category": "internet",
  "display_name": "Global Reachability Score",
  "description": "Tracks passive reachability signals across configured public targets.",
  "tags": ["reachability", "global", "network"],
  "dashboard_priority": 10
}
```

This metadata can live in a future per-observer metadata file, in existing
configuration, or in a generated catalog. The implementation choice should be
made later and should not require observer path changes.

## Proposed assignments for existing observers

These assignments are proposed labels only. They do not imply file moves or
runner changes.

| Observer | Proposed category | Status | Notes |
| --- | --- | --- | --- |
| `area51-reachability` | `internet` | existing | Public reachability signal. |
| `asn-visibility-by-country` | `internet` | existing | Network visibility by country. |
| `cuba-internet-weather` | `internet` | existing | Internet-weather signal focused on Cuba. |
| `dns-time-to-answer-index` | `internet` | existing | DNS timing and responsiveness signal. |
| `dns-tta-stress-index` | `internet` | existing | DNS time-to-answer stress signal. |
| `global-reachability-long-horizon` | `internet` | existing | Long-horizon reachability tracking. |
| `global-reachability-score` | `internet` | existing | Global reachability scoring. |
| `internet-shrinkage-index` | `internet` | existing | Internet reachability contraction signal. |
| `ipv6-adoption-locked-states` | `internet` | existing | IPv6 adoption signal for locked-state contexts. |
| `ipv6-global-compare` | `internet` | existing | Global IPv6 comparison signal. |
| `ipv6-locked-states` | `internet` | existing | IPv6 signal for locked-state contexts. |
| `iran-dns-behavior` | `internet` | existing | DNS behavior signal. |
| `media-language-germany` | `media` | existing | Public media-language signal for Germany. |
| `mx-presence-by-country` | `internet` | existing | Mail exchanger presence by country. |
| `mx-presence-per-country` | `internet` | existing | Mail exchanger presence signal. |
| `north-korea-connectivity` | `internet` | existing | Connectivity signal. |
| `silent-countries-list` | `internet` | existing | Country-level silence/reachability signal. |
| `tls-fingerprint-change` | `internet` | existing | TLS fingerprint change signal. |
| `traceroute-to-nowhere` | `internet` | existing | Routing/path failure signal. |
| `undersea-cable-dependency` | `internet` | existing | Undersea cable dependency signal. |
| `undersea-cable-dependency-map` | `internet` | existing | Undersea cable dependency mapping signal. |
| `world-observer-meta` | `internet` | existing | Repository/observer health metadata for internet observers. |

## Planned category examples

The following names describe planned or conceptual observer families. They are
not path changes and do not require code changes now.

| Planned observer or family | Proposed category | Status | Notes |
| --- | --- | --- | --- |
| `fuel` | `society` | planned | Public fuel price or availability indicators. |
| `electricity` | `society` | planned | Public electricity price, availability, or grid-status indicators. |
| `food` | `society` | planned | Public food price or availability indicators. |
| `housing` | `society` | planned | Public housing cost or availability indicators. |
| `bahn` | `society` | planned | Public rail or transit service indicators. |
| `post` | `society` | planned | Public postal or delivery service indicators. |
| `weather` | `environment` | planned | Public weather observations or forecasts. |
| `climate` | `environment` | planned | Public climate indicators. |
| `natural-disasters` | `environment` | planned | Public hazard, emergency, or disaster indicators. |

## Implementation notes for later

- Prefer metadata-driven categorization over directory restructuring.
- Treat categories as dashboard/reporting concerns, not execution concerns.
- Keep observer outputs stable and JSON-focused.
- If metadata is added to existing observer config files later, migrate one
  observer at a time and preserve backwards compatibility.
- If a central catalog is added later, validate that it does not drift from the
  observer directories present under `observers/`.
