# Wiesmoor Population Observer

Publishes a municipality-level annual population snapshot for Wiesmoor (AGS `03452025`). Values come from official municipal-directory spreadsheets; no unofficial estimate or interpolation is used.

The bundled `source_data.json` preserves the exact reference date, census basis, and official download URL for every point. The observer intentionally suppresses a 2023–2024 year-on-year comparison because the source basis changes from Zensus 2011 to Zensus 2022. Update the reference file only when a newer official year-end municipality result is published.

Run with `python observers/wiesmoor-population/observer.py`. The command prints one JSON object and performs no network request.
