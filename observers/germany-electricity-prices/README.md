# Germany Electricity Prices Observer

Daily descriptive backend/data observer for the existing Electricity Observer website section.

## Representative household

- Country: Germany
- Location: Wiesmoor
- Postal code: 26639
- Annual consumption: 3,500 kWh
- Representative unit: one household
- Observation frequency: daily
- Observation type: descriptive only

## Data-source policy

The observer does not invent or estimate electricity prices. It currently emits a documented static tariff observation for EWE Grundversorgung in Wiesmoor and keeps validated local imports available for future CSV/JSON source integrations. It does not scrape comparison websites, use fake data, guess a market average, or claim undocumented JSON APIs.

Accepted import formats are CSV or JSON records with:

- `date` (`YYYY-MM-DD`)
- `price_eur_per_kwh` (positive decimal, max 2 EUR/kWh)
- `source` (non-empty source label)
- optional `source_url`
- optional `notes`

## Initial static source

- Source type: `static_tariff_observation`
- Supplier: EWE
- Tariff: Grundversorgung / EWE Strom comfort
- Location: Wiesmoor
- Postal code: 26639
- Annual consumption: 3,500 kWh
- Work price: 29.63 ct/kWh
- Base price: 224.80 EUR/year
- Source note: manually configured documented tariff values

Annual and monthly costs are calculated from the configured work price, annual consumption, and base price.
