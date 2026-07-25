# Ocean Buoy Observer

## Purpose and source strategy

Ocean Buoy Observer is an independent, machine-readable view of recent marine observations. Its single authoritative source is NOAA's **National Data Buoy Center (NDBC) latest-observations text feed**. The feed is official, structured, documented, has stable station identifiers, and avoids browser scraping. No second source is merged, so conflicting observations cannot be hidden by field-level precedence.

NDBC includes moored buoys, coastal stations, and other marine platforms operated or received by NOAA. Coverage is predominantly United States waters and partner stations distributed through NDBC; it is **not a complete global buoy catalogue**. `country` and `name` remain `null` because the compact latest feed does not reliably provide them. Authority, source ID, official station link, coarse ocean region, and attribution are explicit.

The deterministic selection accepts a parseable station ID, UTC timestamp, valid coordinates, and an observation no more than 24 hours old. Duplicate IDs keep the newest record (with serialized content as a stable tie-breaker), and output is sorted by ID. A malformed station is skipped without discarding good stations; no valid stations fails the run.

## Schema and units

The top level contains `observer`, `coverage`, `statistics`, `conditions`, `stations`, `sources`, `quality`, `diagnostics`, and `warnings`. Station records contain identity/location, observation age and freshness, provenance, nullable measurements, derived conditions, and availability flags.

Normalized units are decimal degrees and UTC ISO 8601; wind m/s; waves and water level m; periods s; pressure hPa; temperature °C; and visibility km. NDBC `MM`/`N/A` and malformed values become `null`, never zero. The feed already reports wind in m/s; visibility is converted from nautical miles and tide from feet. Plausibility bounds are: direction 0–359°, wind 0–100 m/s, gust 0–150 m/s, wave 0–40 m, periods 0–40 s, pressure 850–1100 hPa, pressure tendency −100–100 hPa, air/dew point −80/−90–60 °C, sea temperature −5–45 °C, visibility 0–1000 km, and water level −20–20 m. Out-of-range optional values become `null`; invalid identity, coordinates, or time rejects that row.

Freshness is `fresh` through 3 hours, `aging` above 3 through 6 hours, and `stale` above 6 through 24 hours. Wave states use WMO sea-state height boundaries: calm (<0.1 m), smooth, slight, moderate, rough, very rough, high, very high, and phenomenal (≥14 m). Wind labels are transparent project thresholds: calm (<0.5), light, moderate, strong, gale, storm, and hurricane-force (≥32.7 m/s). These describe measurements, not safety advice.

## Exports, retention, and failure behavior

* Latest: `data/latest/ocean-buoy-observer.json`
* Consumer/dashboard copy: `dashboard/latest/ocean-buoy-observer.json`
* Full recent snapshots: `data/hourly/ocean-buoy-observer/<UTC timestamp>.json`, retained seven days
* Compact long-term history: `state/ocean-buoy-observer-history/YYYY-MM-DD.json`

Long-term points contain only observer status, generation date, statistics, and coverage—not station arrays. The current UTC day's point is atomically replaced each hour. Pruning is restricted to timestamp-shaped JSON inside the buoy snapshot directory.

The runner captures output to a temporary file, invokes the collector's strict validator, and atomically renames staged files on the destination filesystem. Collection, malformed JSON, explicit error status, bad provenance/coordinates/timestamps/measurements, duplicates, or zero stations exits nonzero before installation and preserves last-known-good files. Per-observer and daily-workflow nonblocking `flock` locks avoid overlap. The dedicated timer is primary; the daily runner deliberately does **not** recollect or archive full buoy arrays. Dashboard export copies the dedicated latest payload.

## Schedule and operation

NDBC latest observations generally update hourly. The persistent systemd timer runs hourly at minute 15 (plus up to 30 seconds jitter), avoiding top-of-hour work and the Earthquake Observer at minute 05. It catches up after downtime without querying more frequently than the practical source cadence.

Development (writes JSON only to stdout; diagnostics/errors use stderr):

```bash
python3 observers/ocean-buoy-observer/observer.py > /tmp/ocean-buoy-observer.json
python3 observers/ocean-buoy-observer/observer.py --validate /tmp/ocean-buoy-observer.json
```

Safe repository one-shot:

```bash
./scripts/run_ocean_buoy_observer_production.sh
```

### worldnode deployment (do not run from development)

```bash
cd /opt/world-observer/world-observer
git pull --ff-only
sudo install -m 0644 deploy/systemd/world-observer-ocean-buoy.service /etc/systemd/system/world-observer-ocean-buoy.service
sudo install -m 0644 deploy/systemd/world-observer-ocean-buoy.timer /etc/systemd/system/world-observer-ocean-buoy.timer
sudo systemctl daemon-reload
sudo systemctl enable --now world-observer-ocean-buoy.timer
systemctl list-timers world-observer-ocean-buoy.timer
sudo systemctl start world-observer-ocean-buoy.service
systemctl status world-observer-ocean-buoy.service --no-pager
journalctl -u world-observer-ocean-buoy.service -n 100 --no-pager
```

Disable/rollback:

```bash
sudo systemctl disable --now world-observer-ocean-buoy.timer
sudo rm -f /etc/systemd/system/world-observer-ocean-buoy.{service,timer}
sudo systemctl daemon-reload
cd /opt/world-observer/world-observer && git checkout <previous-good-commit>
```

Known limitations: NDBC is geographically biased; station type/name/country are absent from the selected feed; reported availability varies by instrument; timestamps are minute-resolution; a coarse ocean region is coordinate-derived; tide is published only when meaningfully present upstream; and hourly snapshots use filesystem modification time for retention.
