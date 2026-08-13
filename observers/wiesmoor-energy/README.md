# Wiesmoor Energy Observer

Reads the official, public Marktstammdatenregister units overview for locality `Wiesmoor` and postal code `26639`, then immediately aggregates the rows by energy-carrier category.

The emitted JSON contains only municipality-level counts, operating-status counts, installed electrical power, and commissioning-year aggregates. It never contains unit names, addresses, operator names, or MaStR identifiers. Installed capacity is explicitly not described as production, generation, consumption, or feed-in. Storage figures are electrical power (kW), not energy (kWh).

Run with `python observers/wiesmoor-energy/observer.py`. A source failure produces an honest `unavailable` payload without synthetic values.
