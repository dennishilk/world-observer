# Horizon Observer

Horizon Observer is a local, API-free astronomy observer for Wiesmoor, East Frisia, Germany. It calculates apparent Sun, Moon, Mercury, Venus, Mars, Jupiter, and Saturn positions against the local geometric horizon.

## Method

The observer uses PyEphem for local astronomical calculations when the `ephem` package is installed. In minimal offline environments where PyEphem is not installed, it uses a deterministic built-in low-precision astronomy fallback so the observer and tests still complete without network access. It does not perform external HTTP requests at runtime and does not download ephemeris files. Calculations are stored internally in UTC; local rise/set timestamps are emitted for `Europe/Berlin`.

Coordinates are the canonical Wiesmoor coordinates already used by the Wiesmoor Sky Observer: latitude `53.4167`, longitude `7.7333`, elevation about `8 m`.

## Output conventions

The runner writes the observer stdout to:

- `data/daily/<YYYY-MM-DD>/horizon-observer.json`
- `data/latest/horizon-observer.json`
- `dashboard/latest/horizon-observer.json` after dashboard export

Major sections include `summary`, `sky_state`, `orientation`, `objects`, `horizon_scene`, `constellations`, `milky_way`, `iss`, `diagnostics`, and `sources`.

## Coordinate conventions

Altitude is astronomical altitude in degrees. Negative altitudes are preserved for below-horizon objects. Azimuth is normalized to `0 <= azimuth < 360`, measured from north through east. Compass labels use 16 equal 22.5° sectors with north centered on 0°; boundaries are 11.25°, 33.75°, 56.25°, and so on.

## Limitations

- The horizon is geometric and does not model buildings, trees, or terrain obstruction.
- Refraction is disabled by setting observer pressure to zero for deterministic geometric values.
- Constellation labels are approximate anchor points, not official IAU constellation boundaries.
- The Milky Way path is an approximate Galactic-equator path. Real visibility depends on darkness, weather, moonlight, and light pollution.
- ISS support is optional. If `data/reference/iss.tle` is absent, the observer reports `local_tle_missing` and continues without network access.

## Manual run

```bash
python observers/horizon-observer/observer.py > /tmp/horizon-observer.json
python -m json.tool /tmp/horizon-observer.json >/dev/null
```

For deterministic runs, set `WORLD_OBSERVER_NOW_UTC`, for example:

```bash
WORLD_OBSERVER_NOW_UTC=2026-01-15T21:00:00Z python observers/horizon-observer/observer.py
```

## Tests

```bash
pytest tests/test_horizon_observer.py
```
