# Earthquake Observer data contract (Phase 2)

The Earthquake Observer is a calm, descriptive view of earthquakes present in a current public catalog. It records observations and does not predict earthquakes, estimate danger, report impacts, or classify activity as normal, elevated, or unusual.

The frontend lives in `dennishilk.github.io`. The collector and normalized exports live in `dennishilk/world-observer`.

## Source and schedule

The observer uses the official USGS Earthquake Hazards Program real-time GeoJSON summary feed, **all earthquakes, past day**:

`https://earthquake.usgs.gov/earthquakes/feed/v1.0/summary/all_day.geojson`

It runs with the existing daily observer workflow at 02:00 UTC. It does not add a separate or aggressive polling timer. The source is downloaded over HTTPS with a 20-second timeout, three bounded attempts, a project User-Agent, HTTP/JSON validation, and a 10 MiB response limit.

## Export and publication

Schema version 1 is first stored as `data/latest/earthquake-observer.json`, then exported as `dashboard/latest/earthquake-observer.json`. The existing dashboard publisher copies it to `/srv/www/dennishilk.github.io/world-observer/dashboard/latest/earthquake-observer.json` when configured with that website checkout. A source/validation failure exits unsuccessfully, records the normal daily error result, and does not replace an existing last-known-good latest earthquake export.

The normalized document contains source, source-generation and collection timestamps; a 24-hour window; summary; events; hourly activity; magnitude and depth distributions; unavailable historical context; compact quality counts; diagnostics; and notes. Only source features whose `properties.type` is exactly `earthquake` are included. Required values are a stable ID, finite magnitude, parseable event time, longitude in −180…180, latitude in −90…90, and finite non-negative depth. Coordinates follow GeoJSON/USGS order: longitude, latitude, depth. Optional missing place text becomes `Region not provided`. Event links are retained only for HTTPS hosts at `earthquake.usgs.gov` or its subdomains. Duplicate IDs retain the valid representation with the newest source update time. Events are newest-first and out-of-window events are counted but excluded.

Statuses are `live` for a fully usable non-empty feed, `partial` when usable output required filtering or timing fallback, and `empty` for a valid feed with no accepted in-window earthquake events. `empty` describes the selected feed, not every earthquake on Earth. The source generation time defines the half-open 24-hour window when valid; otherwise collection time is an explicit fallback. Activity contains 24 contiguous, one-hour UTC buckets, includes zeros, and assigns events with `start <= time < end` exactly once.

Magnitude bins are `< 1.0`, `1.0–< 2.0`, `2.0–< 3.0`, `3.0–< 4.0`, `4.0–< 5.0`, `5.0–< 6.0`, and `>= 6.0`. Depth categories are shallow (0–70 km inclusive), intermediate (>70–300 km), deep (>300–700 km), and out of range (>700 km).

Catalog completeness varies by region, monitoring-network density, depth, background noise, processing/review state, and magnitude. The count is the number of accepted events in the selected USGS feed, not a complete count of every earthquake occurring worldwide.

A verified historical baseline and any historical comparison are deferred to a later phase. Phase 2 adds no long-term catalog, activity classification, plate overlays, sequence/aftershock analysis, impact interpretation, or predictive model.
