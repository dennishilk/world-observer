# Wiesmoor Groundwater Observer

Selects the nearest usable official NLWKN groundwater station to the Wiesmoor reference point and publishes a short daily history. At present the official station list contains no station explicitly identified as Wiesmoor, so the payload and website must label the result **Regional reference station / Regionale Referenzmessstelle**.

The adapter follows the public NLWKN web-service documentation, handles its documented coordinate-field reversal, and rejects source sentinel values such as `-777` and `-888`. Any displayed groundwater class is copied from NLWKN; this observer invents no warning or critical thresholds.

Run with `python observers/wiesmoor-groundwater/observer.py`. A source failure produces an `unavailable` payload without fallback measurements.
