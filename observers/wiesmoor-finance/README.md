# Wiesmoor City Finance Observer

Publishes a maintained snapshot of the City of Wiesmoor's official 2026 budget document. Every reporting period carries one explicit value status:

- `ACTUAL` — `Rechnungsergebnis` in the source document
- `PLAN` — a budget-year `Ansatz`
- `FORECAST` — a future amount in the medium-term financial plan

The observer validates that result-budget and cash-flow totals reconcile before emitting JSON. It performs no PDF scraping during the daily run; update `source_data.json` only from a newer official budget or annual-result document and preserve its source URL and status labels.

Run with `python observers/wiesmoor-finance/observer.py`.
