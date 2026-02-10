# undersea-cable-dependency-map

## Purpose
This observer computes country-level **dependency** and **redundancy** metrics from a static undersea cable dataset (GeoJSON/JSON/CSV) without active probing.

## Dataset and licensing
- Intended source: an openly licensed submarine-cable dataset (for example, a derivative of Greg's Cable Map where redistribution terms are respected).
- Raw files are cached locally under `observers/undersea-cable-dependency-map/.cache/` and must remain untracked.
- You can also point `config.json` to a local dataset path via `dataset_path`.

## Metric definitions
Per country, daily:
- `landing_count`: count of cable landing occurrences attributed to that country in dataset metadata.
- `cable_count`: number of cable records where the country appears.
- `unique_partner_countries`: number of distinct partner countries appearing on multi-country cables.
- `redundancy_score` in `[0..1]`: higher implies more landings/cables/partners and lower concentration.
- `dependency_score` in `[0..1]`: inverse of redundancy; higher implies thinner external cable diversity.

The observer keeps outputs aggregated and does not publish routes, landing coordinates, or per-cable lists.

## Significance and PNG policy
`data/latest/chart.png` is generated **only** when significance is true:
- dataset hash changed (`dataset updated`), or
- top-country metric structure changed beyond configured thresholds.

Because static infrastructure datasets change rarely, PNGs are expected to be rare.

## Tracked outputs
- Daily: `data/daily/YYYY-MM-DD/undersea-cable-dependency-map.json`
- Latest summary: `data/latest/summary.json`
- Significant-only PNG: `data/latest/chart.png`
