# World-Observer Operational Audit (2026-02-18)

## Scope
- Audited `data/latest` and `data/daily/2026-02-18` outputs.
- Deep-reviewed and hardened:
  - `area51-reachability`
  - `north-korea-connectivity`
  - `dns-tta-stress-index`
  - orchestrator: `scripts/run_daily.py`
  - meta observer: `world-observer-meta`

## Observer health snapshot

### Stable
- cuba-internet-weather
- dns-time-to-answer-index
- dns-tta-stress-index
- global-reachability-score
- ipv6-adoption-locked-states
- mx-presence-by-country
- mx-presence-per-country
- north-korea-connectivity
- silent-countries-list
- tls-fingerprint-change
- undersea-cable-dependency
- undersea-cable-dependency-map

### Degraded
- area51-reachability (`data_status=unavailable`)
- asn-visibility-by-country (`data_status=unavailable`)
- global-reachability-long-horizon (`data_status=partial`)
- internet-shrinkage-index (`data_status=partial`)
- ipv6-global-compare (`data_status=unavailable`)
- ipv6-locked-states (`data_status=unavailable`)
- traceroute-to-nowhere (`data_status=unavailable`)

### Unreliable
- iran-dns-behavior (`status=error` in daily run)

## Anomalies detected
- Mixed status semantics across observers (`status=error` vs `data_status=*`).
- Missing diagnostics in many observer payloads before hardening.
- Partial/unavailable observer outputs were not summarized as degraded in meta.
- Potential baseline freeze behavior where `std=0` could suppress significance movement.
- Corrupted JSON files in daily output directories were previously undetected before meta execution.

## Fixes applied

### 1) area51-reachability hardening
- Added deterministic request diagnostics (`api_attempts`, `retries`, `http_status`, `endpoint`, `last_error`).
- Added HTTP-aware behavior:
  - deterministic stop on 4xx
  - retry with exponential backoff on retryable failures.
- Classified `empty_but_reachable` case explicitly.
- Added `effective_std` fallback for zero-std baselines to reduce baseline lock behavior.
- Chart generation now guarded by `WORLD_OBSERVER_ENABLE_CHARTS=1` to avoid runtime instability from optional plotting stack.

### 2) dns-tta-stress-index hardening
- Added retry attempts for DNS query path.
- Added per-query and aggregate diagnostics counters.
- Added top-level diagnostics object in observer JSON output.

### 3) north-korea-connectivity hardening
- Added aggregate diagnostics counters at observer level.
- Added deterministic `data_status=error` when no targets are configured.
- Preserved existing layered probe semantics.

### 4) run_daily hardening
- Added payload normalization to enforce consistent `data_status` values (`ok|partial|unavailable|error`).
- Added diagnostics fallback insertion for observer outputs that omit diagnostics.
- Added corrupted JSON scan for daily directory before meta run completion reporting.
- Added cron-safe file logging to `logs/cron.log`.

### 5) meta observer hardening
- Added degraded observer detection (`observers_degraded`).
- Added degraded observer anomaly summary to `notes`.
- Continued separation of missing vs failed vs degraded inputs.

## Remaining risk areas
- External provider instability remains a source of `unavailable/partial` for externally dependent observers.
- `iran-dns-behavior` still exits non-zero and requires observer-specific remediation.
- Some observers still rely on network behavior that can legitimately return all-zero measurements; this is now better diagnosed but not fully avoidable.

## Confirmation
- `data_status` normalization is now enforced in orchestrator write path.
- Retry handling is improved in audited observers.
- Meta output now flags degraded observers and includes anomaly summaries in notes.
- Silent failures are reduced via diagnostics enrichment + corrupted JSON detection + explicit error payload fallback.
