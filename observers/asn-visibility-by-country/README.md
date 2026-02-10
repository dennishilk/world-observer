# asn-visibility-by-country

## Purpose
This observer passively estimates daily ASN visibility **by country** from public
BGP RIB snapshots. It does not probe hosts or networks directly.

## Data sources
- RIPE RIS and/or RouteViews RIB snapshots (MRT files).
- CAIDA AS Organizations (AS2Org) dataset for ASN → organization → country mapping.

## Processing model
1. Select a RIB snapshot in the configured UTC window.
2. Parse MRT and extract unique ASNs observed in AS_PATH attributes.
3. Map each ASN to a country via CAIDA AS2Org organization-country.
4. Aggregate to per-country `asn_visible_count` and discard ASN lists.

The country mapping is an **organization-country proxy**, not necessarily the
physical location of all routed infrastructure.

## Privacy and retention constraints
- Tracked outputs include only country-level counts and derived statistics.
- No prefixes, no AS_PATHs, no ASN lists are written to tracked outputs.
- Raw downloads and parse intermediates stay in local cache directories
  (`.cache/`) and are gitignored.

## Significance model
For each country:
- 30-day baseline mean/std
- z-score and percent step change

A country is significant when either threshold triggers:
- `abs(z) > sigma_mult`
- `abs(delta_pct) >= step_threshold_pct`

Mass event triggers when `significant_count >= mass_event_k`.

## PNG policy
`data/latest/chart.png` is generated **only** on significant days. The file is
overwritten on each significant event and omitted from summary metadata when no
chart is produced.
