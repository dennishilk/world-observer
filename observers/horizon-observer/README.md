# Horizon Observer

Horizon Observer is a local, API-free astronomy observer for Wiesmoor, East Frisia, Germany. It calculates apparent Sun, Moon, Mercury, Venus, Mars, Jupiter, and Saturn positions against the local geometric horizon.

## Runtime architecture

The normal daily World Observer run remains supported, but Horizon also has a dedicated production path for live displays. `world-observer-horizon.timer` runs every 10 minutes because horizon positions and ISS passes change quickly enough that daily JSON is not suitable for a live sky display.

Core astronomy remains local. The observer does not perform network requests during observation and reports `external_api_requests: 0` and `local_network_requests: 0`.

ISS support uses a locally cached TLE at `data/reference/iss.tle`. The observer reads the cache with PyEphem (`ephem.readtle`) and calculates current altitude/azimuth plus the next geometric pass for Wiesmoor. The observation process never downloads TLE data.

A separate low-frequency updater, `world-observer-iss-tle.timer`, refreshes the TLE every 6 hours using `scripts/update_iss_tle.py`. Download success is intentionally not coupled to every 10-minute Horizon run; old valid data is retained on updater failures.

## Outputs

- `data/daily/<YYYY-MM-DD>/horizon-observer.json` from the daily run
- `data/latest/horizon-observer.json`
- `dashboard/latest/horizon-observer.json`
- `/srv/www/dennishilk.github.io/world-observer/dashboard/latest/horizon-observer.json` from the 10-minute production script

Major sections include `summary`, `sky_state`, `orientation`, `objects`, `horizon_scene`, `constellations`, `milky_way`, `iss`, `diagnostics`, and `sources`.

## ISS TLE freshness policy

- `fresh`: TLE epoch age is <= 3 days
- `aging`: age is > 3 and <= 7 days
- `stale`: age is > 7 days
- `invalid`: local TLE parsing or validation failed
- `missing`: no local TLE exists

Missing, invalid, and stale TLE data are non-fatal. ISS is optional and does not downgrade otherwise valid Sun/Moon/planet data from `ok`. Stale TLE data is reported, but exact current ISS position and next-pass data are not exposed as trustworthy.

## Failure behaviour

`scripts/run_horizon_observer_production.sh` uses a lock, validates generated JSON, and installs it with temporary files plus atomic renames. It updates only Horizon JSON paths and preserves the last valid JSON if a new observer execution or JSON validation fails. It also checks the daily production lock and skips cleanly if the daily run is active.

The 10-minute workflow does **not** run `git add`, `git commit`, or `git push`. The frequently changing Horizon JSON is runtime output served directly from `/srv/www/dennishilk.github.io`.

## systemd installation on worldnode

```bash
sudo cp deploy/systemd/world-observer-horizon.service /etc/systemd/system/
sudo cp deploy/systemd/world-observer-horizon.timer /etc/systemd/system/
sudo cp deploy/systemd/world-observer-iss-tle.service /etc/systemd/system/
sudo cp deploy/systemd/world-observer-iss-tle.timer /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now world-observer-horizon.timer
sudo systemctl enable --now world-observer-iss-tle.timer
```

Manual execution:

```bash
sudo systemctl start world-observer-horizon.service
sudo systemctl start world-observer-iss-tle.service
```

Inspect timers and logs:

```bash
systemctl status world-observer-horizon.timer --no-pager
systemctl list-timers --all | grep horizon
journalctl -u world-observer-horizon.service -n 100 --no-pager
systemctl status world-observer-iss-tle.timer --no-pager
systemctl list-timers --all | grep iss-tle
journalctl -u world-observer-iss-tle.service -n 100 --no-pager
```

## Local development

```bash
python observers/horizon-observer/observer.py > /tmp/horizon-observer.json
python -m json.tool /tmp/horizon-observer.json >/dev/null
WORLD_OBSERVER_NOW_UTC=2026-01-15T21:00:00Z python observers/horizon-observer/observer.py
pytest tests/test_horizon_observer.py tests/test_horizon_production_runtime.py tests/test_iss_tle_updater.py
```

Angles are degrees. Negative altitudes are preserved for below-horizon objects. Azimuth is normalized to `0 <= azimuth < 360`, measured from north through east. Compass labels use 16 equal 22.5° sectors with north centered on 0°.

Limitations: the horizon is geometric and does not model buildings, trees, terrain obstruction, weather, or light pollution; ISS pass data is geometric and is not a naked-eye visibility prediction unless additional darkness and sunlit-state logic is added.
