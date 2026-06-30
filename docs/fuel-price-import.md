# Germany fuel price historical imports

The `germany-fuel-prices` observer supports historical import files prepared outside the daily run, for example on Cthulhu, in `imports/fuel-prices-germany/`.

## Supported fuel types

Only fuel types emitted by the daily observer are accepted:

| `fuel_type` | Meaning |
| --- | --- |
| `benzin` | Super E5 |
| `diesel` | Diesel |
| `super_e10` | Super E10 |

Super Plus is not accepted unless a reliable public source is added later.

## Daily data source and environment

Current daily observations use the public Tankerkoenig/MTS-K-derived API when configured:

- `WORLD_OBSERVER_FUEL_API_KEY` — required for live fuel API access.
- `WORLD_OBSERVER_FUEL_LAT` — optional sample center latitude, default `51.1657`.
- `WORLD_OBSERVER_FUEL_LNG` — optional sample center longitude, default `10.4515`.
- `WORLD_OBSERVER_FUEL_RADIUS_KM` — optional sample radius, default `25`.

When the API key is absent or the source cannot be fetched, the observer exports `status: unavailable`, `data_status: unavailable`, and a clear `degraded_reason`. It does not invent prices.

## Import formats

JSON imports may be either a list of records or an object with a `records` list. CSV imports must use the same column names.

Required fields:

- `date` — `YYYY-MM-DD`.
- `fuel_type` — one of `benzin`, `diesel`, `super_e10`.
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

Daily generated observer state wins over imported duplicate `(date, fuel_type)` records. Imports are never allowed to overwrite `state/germany-fuel-prices/YYYY-MM-DD.json`.

## Validation and diagnostics

Malformed files, malformed rows, unsupported fuel types, invalid prices, invalid granularities, and duplicate imported dates are ignored. Diagnostics are reported in `import_diagnostics` in the observer payload and dashboard society export.

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

Imported history affects historical averages, min/max, record high/low, and long-term comparisons only.
