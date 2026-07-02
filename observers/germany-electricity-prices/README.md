# Germany Electricity Prices Observer

Daily descriptive backend/data observer for the existing Electricity Observer website section.

## Representative household

- Country: Germany
- Location: Wiesmoor
- Postal code: 26628
- Annual consumption: 3,500 kWh
- Representative unit: one household
- Observation frequency: daily
- Observation type: descriptive only

## Data-source policy

The observer does not invent or estimate electricity prices. It currently emits an `unavailable` payload unless validated local imports are supplied in `imports/germany-electricity-prices/`.

Accepted import formats are CSV or JSON records with:

- `date` (`YYYY-MM-DD`)
- `price_eur_per_kwh` (positive decimal, max 2 EUR/kWh)
- `source` (non-empty source label)
- optional `source_url`
- optional `notes`

This placeholder exists because no stable redistributable public tariff source is configured for a Wiesmoor household using 3,500 kWh/year.
