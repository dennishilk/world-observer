# Germany fuel price historical imports

The `germany-fuel-prices` observer supports historical import files prepared outside the daily run, for example on Cthulhu, in `imports/fuel-prices-germany/`.

## Supported fuel types

Only fuel types emitted by the daily observer are accepted:

| `fuel_type` | Meaning |
| --- | --- |
| `benzin` | Super E5 |
| `diesel` | Diesel |

Super E10 and Super Plus are not accepted. Super E10 fallback parsing is intentionally disabled because fallback values are not reliable enough for publication.

## Daily data source and compliance behavior

Public World Observer Fuel automatically attempts one public nationwide daily average fuel-price page fetch during each daily run. The fetch is best-effort and only accepts explicitly labeled, positive euro-per-liter prices for the supported fuels. Google AI Overview text must never be used as a source. Historical imports remain authoritative for the same date.

Default production behavior:

- The observer fetches public daily average pages once per daily run from `WORLD_OBSERVER_FUEL_PUBLIC_URL` or the built-in NDR public average page.
- The observer does **not** automatically fetch Tankerkönig/MTS-K API data, even if `WORLD_OBSERVER_FUEL_API_KEY` is present.
- A local import row for the run date wins over a public-page fetched value for the same fuel.
- If public-page fetch or parsing fails, the observer falls back to permitted local imports.
- If neither public-page fetch nor imports produce a price, the observer exports `status: unavailable`, `data_status: unavailable`, and a clear `degraded_reason`.
- The observer does not invent, synthesize, or fake fuel prices.

## Optional manual/local Tankerkönig API mode

Tankerkönig API support is retained only for optional manual/local tests. Do not use it for public automated daily dashboard aggregation unless you have explicit permission for that use.

- `WORLD_OBSERVER_FUEL_API_KEY` — optional for manual local API access only; it must never be committed.
- `WORLD_OBSERVER_FUEL_ENABLE_TANKERKOENIG_API=1` — required opt-in for a manual/local API fetch.
- `WORLD_OBSERVER_FUEL_LAT` — optional sample center latitude, default `51.1657`.
- `WORLD_OBSERVER_FUEL_LNG` — optional sample center longitude, default `10.4515`.
- `WORLD_OBSERVER_FUEL_RADIUS_KM` — optional sample radius, default `25`.

Tankerkönig-derived data is licensed under CC BY 4.0, so World Observer outputs or imports that use Tankerkönig-derived data must include the required attribution.

## Import formats

JSON imports may be either a list of records or an object with a `records` list. CSV imports must use the same column names.

Required fields:

- `date` — `YYYY-MM-DD`.
- `fuel_type` — one of `benzin`, `diesel`.
- `price_eur_per_liter` — numeric euro-per-liter price.
- `source` — source label.
- `granularity` — `daily`, `monthly`, or `yearly`.

Optional fields:

- `source_url`
- `notes`

Example JSON:

```json
{
  "records": [
    {
      "date": "2024-01-01",
      "fuel_type": "diesel",
      "price_eur_per_liter": 1.72,
      "source": "Cthulhu prepared public history",
      "source_url": "https://example.invalid/source",
      "granularity": "daily",
      "notes": "Daily national average prepared offline"
    }
  ]
}
```

Example CSV header:

```csv
date,fuel_type,price_eur_per_liter,source,source_url,granularity,notes
```

## Duplicate precedence

Manual API results for the current run win over imported duplicate `(date, fuel_type)` records. Public average fetches do not override same-day local imports. In default production mode, imports are preferred and old generated state is not used as a public dashboard source.

## Validation and diagnostics

Malformed files, malformed rows, unsupported fuel types, invalid prices, invalid granularities, and duplicate imported dates are ignored. Import diagnostics are reported in `import_diagnostics` in the observer payload and dashboard society export. Fetch diagnostics include `source`, `fetch_url`, `fetched_at_utc`, `parse_status`, `fallback_used`, and `degraded_reason` when unavailable or degraded. The production observer does not perform E10 fallback parsing and never publishes suspicious fallback values.

## How Cthulhu can prepare files

Cthulhu can normalize any reliable public historical source into JSON or CSV using the fields above, place files in `imports/fuel-prices-germany/`, and leave daily `state/` untouched. Monthly or yearly rows should use a representative date such as the first day of the period and set `granularity` accordingly.

## Verification

Run:

```bash
python -m pytest -q
python scripts/export_dashboard.py
jq '.observers[] | select(.observer=="germany-fuel-prices")' dashboard/society.json
cat data/latest/germany-fuel-prices.json | jq .
```

Imported history is the default public dashboard source and affects current displayed import-derived prices, historical averages, min/max, record high/low, and long-term comparisons.
