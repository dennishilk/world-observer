# World Observer Reactivation Audit — 2026-06-28

## Repository audit summary

World Observer is a Python-based daily observation pipeline. The daily runner executes a fixed list of observers, captures each observer's stdout as JSON, writes canonical daily artifacts under `data/daily/YYYY-MM-DD/`, updates rolling artifacts under `data/latest/`, and then runs `world-observer-meta` to summarize the daily outputs.

The project currently contains 20 configured daily observers plus the meta observer. Every configured daily observer directory has an `observer.py` entrypoint, and `world-observer-meta` is intentionally not part of the daily observer list.

## Current architecture summary

- `scripts/run_daily.py` owns the authoritative daily observer list, date selection, subprocess execution, payload normalization, daily writes, latest-copy refresh, and meta invocation.
- Each observer is a standalone Python script expected to emit one JSON object on stdout.
- `observers/world-observer-meta/observer.py` reads the daily directory from `WORLD_OBSERVER_DAILY_DIR` and emits one summary JSON object on stdout.
- `scripts/heartbeat_push.py` writes hourly heartbeat files under `state/heartbeat/`, keeps only the latest 12 heartbeat JSON files, commits heartbeat changes, and pushes to `origin`.
- `setup_world_observer.sh` is the newer Debian setup path and is parameterized around the invoking sudo user, while `cron/daily.cron` is an older hardcoded example.
- `visualizations/generate_significance_png.py` is a downstream optional chart/significance artifact generator, separate from observer stdout contracts.

## Observer inventory

| Observer | `observer.py` present | Notes |
| --- | --- | --- |
| `area51-reachability` | yes | Performs external aircraft data fetches; current tests reveal a return-contract mismatch in `_fetch_aircraft`. |
| `asn-visibility-by-country` | yes | Uses external internet registry-style inputs; latest sample is `data_status: unavailable`. |
| `cuba-internet-weather` | yes | Network/socket/subprocess observer. |
| `dns-time-to-answer-index` | yes | Requires `dnspython`. |
| `dns-tta-stress-index` | yes | DNS/network-derived stress metric. |
| `global-reachability-long-horizon` | yes | Depends on historical daily outputs. |
| `global-reachability-score` | yes | Network reachability observer. |
| `internet-shrinkage-index` | yes | Depends on historical outputs/baselines. |
| `ipv6-adoption-locked-states` | yes | IPv6 resolution/socket observer. |
| `ipv6-global-compare` | yes | Depends on IPv6 historical/comparison data. |
| `ipv6-locked-states` | yes | External URL/data source usage; latest sample is unavailable. |
| `iran-dns-behavior` | yes | Requires `dnspython`. |
| `mx-presence-by-country` | yes | Placeholder/static-style MX metric. |
| `mx-presence-per-country` | yes | DNS/socket MX metric. |
| `north-korea-connectivity` | yes | Socket/SSL/subprocess network observer. |
| `silent-countries-list` | yes | Baseline/history-derived observer. |
| `tls-fingerprint-change` | yes | Socket/SSL observer. |
| `traceroute-to-nowhere` | yes | Depends on host traceroute availability for full behavior. |
| `undersea-cable-dependency` | yes | Socket/subprocess dependency metric. |
| `undersea-cable-dependency-map` | yes | Downloads or derives cable-map style data. |
| `world-observer-meta` | yes | Meta observer; invoked after daily observers and writes no file directly. |

## Broken or inconsistent names

- `data/latest/tls-fingerprint-change-watcher.json` exists, but `tls-fingerprint-change-watcher` is not in the configured observer list and no matching observer directory exists. Treat it as a stale artifact unless a historical compatibility decision says otherwise.
- `cron/daily.cron` calls `scripts/run_daily_cron.py`, but this file is not present. The maintained runner is `scripts/run_daily.py`.
- `cron/daily.cron` is hardcoded to `/home/nebu/world-observer`; `setup_world_observer.sh` is more portable and defaults to the invoking sudo user.
- README text says daily execution is at 02:00 UTC, while `setup_world_observer.sh` installs a daily cron at `5 2 * * *` and `cron/daily.cron` installs `0 2 * * *`.

## Expected output contract

- A daily observer must print JSON only to stdout.
- Diagnostics, retries, and transient errors must go to stderr or logs, not stdout.
- The stdout JSON root must be an object.
- The runner writes `data/daily/YYYY-MM-DD/<observer>.json` for every configured observer.
- The runner normalizes missing or invalid `data_status` to `ok` unless top-level `status` is `error`.
- The runner ensures `diagnostics.api_attempts`, `diagnostics.retries`, and `diagnostics.http_status` exist.
- `world-observer-meta` emits summary JSON to stdout; the runner persists it as `summary.json` and renders `summary.md`.

## Current daily runner behavior

- Default date is yesterday UTC. `--date YYYY-MM-DD` overrides this.
- Without `--date`, if a daily directory already has all configured observer JSON files plus `summary.json` and `summary.md`, the run exits early.
- Each observer is run with `WORLD_OBSERVER_DATE_UTC` set.
- Failures are converted into deterministic per-observer JSON error payloads.
- Invalid observer JSON also becomes a deterministic error payload.
- After observers run, corrupted JSON in the daily directory is detected and logged.
- Meta runs after the observer loop with `WORLD_OBSERVER_DAILY_DIR` set.
- `data/latest/` is updated by copying all daily JSON files except `summary.json`; this means `data/latest/summary.json` can become stale if no observer writes it separately.
- The script prints failure information but exits with status 0 even when failures occur.

## Heartbeat behavior

- Writes one hourly heartbeat JSON file named `YYYY-MM-DDTHHZ.json` in `state/heartbeat/`.
- Keeps only the latest 12 heartbeat files.
- Stages `state/heartbeat`, commits if there are staged heartbeat changes, and pushes `origin HEAD`.
- It hardcodes the deploy key path as `/home/nebu/.ssh/deploy_key`, unlike `setup_world_observer.sh` and `scripts/git_publish.sh`, which use `/home/<user>/.ssh/id_ed25519_world_observer` by default.
- It sets `BatchMode=yes`, so SSH auth should fail non-interactively rather than prompting for username/password.

## GitHub Pages/dashboard artifacts

- `data/latest/` contains website/dashboard-friendly JSON snapshots and a `chart.png`.
- `visualizations/generate_significance_png.py` can create significant-event PNG artifacts under `visualizations/significant/` and tracks state in `visualizations/significant_state.json`.
- No dedicated GitHub Pages build system or static site generator was found in the audited files.

## Dependency findings

Declared Python dependencies are minimal: `dnspython`, `matplotlib`, and `pillow`.

Potential host/package dependencies include:

- Python 3 venv tooling.
- `git`, `openssh-client`, cron or systemd timers.
- `traceroute` or equivalent host network tool for traceroute-based observers.
- Network egress and DNS access for live observers.
- Fonts for PNG generation.

The repository has `.python-version` set to `3.12.12`. The audit environment had 3.12.13 installed but not 3.12.12, so unqualified `python` and `pytest` failed through pyenv. Debian 13 reactivation should prefer the system `python3`/venv path or update/remove `.python-version` after confirming the target interpreter.

## Hardcoded paths and users

- `scripts/heartbeat_push.py` hardcodes `/home/nebu/.ssh/deploy_key`.
- `cron/daily.cron` hardcodes `/home/nebu/world-observer` and references a missing runner.
- README examples use `~/world-observer`, which is acceptable as an example but should not be treated as a fixed path.
- `setup_world_observer.sh` is mostly user/path-parameterized via `SUDO_USER`, `REPO_DIR`, and related variables.

## APIs and signals likely to be unstable

- Aircraft/ADS-B style endpoints used by `area51-reachability` may be rate-limited, unavailable, schema-changing, or legally/operationally constrained.
- DNS and network reachability observers are sensitive to local resolver, ISP, firewall, IPv6, and ICMP/traceroute policy.
- Public internet registry/routing/cable datasets can change format or availability.
- TLS fingerprint observations can vary due to normal certificate rotations, CDN behavior, SNI handling, and local network interception.
- Geo/network country-level inference should be treated as an observational signal, not ground truth.

## Problems found

1. Tests currently fail: `test_fetch_aircraft_retries_emit_stderr_only` expects `_fetch_aircraft(...)` to return `None` on failure, but the implementation returns a tuple containing diagnostics.
2. `.python-version` points to `3.12.12`, which was unavailable in the audit environment, breaking plain `python` and `pytest` commands under pyenv.
3. `scripts/heartbeat_push.py` uses a hardcoded `/home/nebu/.ssh/deploy_key` path.
4. `cron/daily.cron` references `/home/nebu/world-observer` and missing `scripts/run_daily_cron.py`.
5. `data/latest/summary.json` is not refreshed by `scripts/run_daily.py` because `_update_latest()` skips `summary.json`.
6. The runner does not exit non-zero on observer/meta failures, so cron/systemd may report success for degraded daily runs.
7. Meta currently has `observers_run`, `observers_missing`, and `observers_degraded`, but failed inputs are only embedded in `notes`; a structured `observers_failed` field would be more reliable.
8. Chart generation is not gated by a single clear environment flag in the cron/setup path.
9. Stale latest artifact `tls-fingerprint-change-watcher.json` can confuse dashboards or audits.

## Recommended immediate fixes

1. Make heartbeat deploy-key selection portable: use `WORLD_OBSERVER_DEPLOY_KEY`, then `$HOME/.ssh/id_ed25519_world_observer`, and only fall back to legacy paths if necessary.
2. Replace or remove `cron/daily.cron`; if kept, make it a template that uses repo-relative commands and `scripts/run_daily.py`.
3. Decide whether `data/latest/summary.json` should always mirror the latest daily `summary.json`; if yes, stop skipping it in `_update_latest()`.
4. Make `scripts/run_daily.py` return a non-zero exit code when failures occur, while still writing deterministic error JSON for each failed observer.
5. Add structured `observers_failed` to `summary.json` and keep `notes` human-readable.
6. Normalize observer status vocabulary around `data_status in {ok, partial, unavailable, error}` and optional top-level `status`.
7. Fix either the Area 51 test expectation or `_fetch_aircraft` contract so diagnostics are preserved without breaking callers.
8. Add `WORLD_OBSERVER_ENABLE_CHARTS=0/1` and gate visualization generation in operational commands.
9. Remove stale `data/latest/tls-fingerprint-change-watcher.json` after confirming it is not intentionally preserved for backwards compatibility.

## Debian 13 reactivation checklist

```sh
# 1. Install system prerequisites
sudo apt update
sudo apt install -y python3 python3-venv python3-pip git openssh-client ca-certificates jq cron traceroute fonts-dejavu-core fonts-dejavu-extra

# 2. Clone as the intended service user; do not assume a fixed username
git clone git@github.com:<owner>/<repo>.git ~/world-observer
cd ~/world-observer

# 3. Create and activate a virtualenv
python3 -m venv .venv
. .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt

# 4. Set a noninteractive Git identity for automation
git config user.name "world-observer"
git config user.email "observer@localhost"

# 5. Configure deploy-key SSH, then verify noninteractive GitHub access
ssh -o BatchMode=yes -T git@github.com || test "$?" = "1"
git ls-remote origin >/dev/null

# 6. Run one observer manually and verify stdout is JSON-only
WORLD_OBSERVER_DATE_UTC=$(date -u +%F) python observers/dns-time-to-answer-index/observer.py > /tmp/dns-time-to-answer-index.json
jq type /tmp/dns-time-to-answer-index.json

# 7. Run the full daily runner manually for an explicit test date
python scripts/run_daily.py --date $(date -u +%F)

# 8. Inspect canonical daily and latest outputs
find data/daily/$(date -u +%F) -maxdepth 1 -type f | sort
jq '.observer, .data_status?' data/daily/$(date -u +%F)/dns-time-to-answer-index.json
find data/latest -maxdepth 1 -type f | sort

# 9. Test meta summary directly
WORLD_OBSERVER_DATE_UTC=$(date -u +%F) WORLD_OBSERVER_DAILY_DIR="$PWD/data/daily/$(date -u +%F)" python observers/world-observer-meta/observer.py | jq .

# 10. Test heartbeat without password prompts
GIT_SSH_COMMAND="ssh -o BatchMode=yes" python scripts/heartbeat_push.py
```

For scheduling, prefer a user-level or system-level systemd timer over cron on a modern Debian/Cockpit host because status, logs, restarts, and failure visibility are easier to inspect in Cockpit. Cron is acceptable for the first reactivation if the commands are kept simple and noninteractive.

## Hardening recommendations

- Enforce JSON-only stdout with tests that run every observer as a subprocess and parse stdout.
- Send diagnostics to stderr or logs only.
- Preserve deterministic error JSON from the runner for all observer failures.
- Use explicit retry/backoff wrappers for external HTTP/DNS APIs and capture attempts in `diagnostics`.
- Ensure all observers emit or are normalized to `data_status: ok|partial|unavailable|error`.
- Make daily runs fail at the process level when any observer fails after artifacts are written.
- Add structured `observers_failed` to meta output.
- Keep `summary.json` reliable and current in both `data/daily/YYYY-MM-DD/` and `data/latest/` if dashboards depend on latest summary.
- Make chart generation optional via `WORLD_OBSERVER_ENABLE_CHARTS`, defaulting to off for initial reactivation.
- Keep chart generation downstream; observers should never depend on PNG generation.

## Future `media-language-germany` observer proposal

Purpose: measure emotionally loaded language in German news coverage over time without claiming manipulation or intent.

Initial metrics:

- `fear_index`
- `crisis_language_score`
- `climate_framing_score`
- `war_language_score`
- `health_alarm_score`
- `economy_alarm_score`

Recommended design:

- Use a transparent source list and store source metadata separately from daily aggregate metrics.
- Count lexicon/category hits per article and normalize by article count and token count.
- Keep the output observational: language intensity and framing frequency, not truth, intent, or manipulation.
- Emit daily JSON with source counts, article counts, token counts, category scores, diagnostics, and `data_status`.
- Preserve enough category-level aggregates for website-ready time series without storing copyrighted article text.
- Prepare future correlation dimensions for Bundestagswahlen, Landtagswahlen, major legislation, DWD weather data, and public event timelines.
- Add methodology documentation before implementation because media-language metrics are more socially sensitive than network measurements.

Candidate output shape:

```json
{
  "observer": "media-language-germany",
  "date": "YYYY-MM-DD",
  "data_status": "ok",
  "article_count": 0,
  "source_count": 0,
  "metrics": {
    "fear_index": 0.0,
    "crisis_language_score": 0.0,
    "climate_framing_score": 0.0,
    "war_language_score": 0.0,
    "health_alarm_score": 0.0,
    "economy_alarm_score": 0.0
  },
  "diagnostics": {
    "api_attempts": 0,
    "retries": 0,
    "http_status": null
  }
}
```

## Docker/Cockpit deployment proposal

Prefer simple host-managed Compose rather than cron inside the container.

### Dockerfile sketch

```Dockerfile
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    WORLD_OBSERVER_ENABLE_CHARTS=0

RUN apt-get update && apt-get install -y --no-install-recommends \
    git openssh-client ca-certificates traceroute fonts-dejavu-core fonts-dejavu-extra \
  && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
RUN mkdir -p /app/data /app/logs /app/state

CMD ["python", "scripts/run_daily.py"]
```

### Compose sketch

```yaml
services:
  world-observer:
    build: .
    working_dir: /app
    environment:
      WORLD_OBSERVER_DATE_UTC: ""
      WORLD_OBSERVER_ENABLE_CHARTS: "0"
      GIT_SSH_COMMAND: "ssh -i /run/secrets/world_observer_deploy_key -o BatchMode=yes -o IdentitiesOnly=yes -o StrictHostKeyChecking=accept-new"
    volumes:
      - world_observer_data:/app/data
      - world_observer_logs:/app/logs
      - world_observer_state:/app/state
    secrets:
      - world_observer_deploy_key
    healthcheck:
      test: ["CMD", "python", "-c", "import json, pathlib; p=pathlib.Path('/app/data/latest'); raise SystemExit(0 if p.exists() else 1)"]
      interval: 1h
      timeout: 10s
      retries: 3
    command: ["python", "scripts/run_daily.py"]

secrets:
  world_observer_deploy_key:
    file: ./secrets/world_observer_deploy_key

volumes:
  world_observer_data:
  world_observer_logs:
  world_observer_state:
```

### Recommended host timers

- Daily run: `docker compose run --rm world-observer python scripts/run_daily.py`, then optionally `docker compose run --rm world-observer python visualizations/generate_significance_png.py`, then `docker compose run --rm world-observer scripts/git_publish.sh`.
- Heartbeat: `docker compose run --rm world-observer python scripts/heartbeat_push.py`.

This keeps scheduling visible in systemd/Cockpit, keeps containers short-lived and debuggable, and avoids hiding cron inside an image.

### Backup strategy

- Back up persistent volumes for `data/`, `logs/`, and `state/`.
- Also back up deploy-key material separately through the server secret-management process.
- Git is not a substitute for raw local backups because ignored raw data and logs may not be committed.

## Exact local test commands after fixes

```sh
PYENV_VERSION=3.12.13 python -m pytest -q
PYENV_VERSION=3.12.13 python scripts/run_daily.py --date 2099-01-01
PYENV_VERSION=3.12.13 python observers/dns-time-to-answer-index/observer.py | jq .
WORLD_OBSERVER_DATE_UTC=2099-01-01 WORLD_OBSERVER_DAILY_DIR="$PWD/data/daily/2099-01-01" PYENV_VERSION=3.12.13 python observers/world-observer-meta/observer.py | jq .
git diff --check
```
