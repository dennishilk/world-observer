# Methodology

## Passive Measurement Principles
World Observer collects only passive, publicly observable signals. Observers do
not initiate network connections, scan hosts, or probe services. Instead, they
rely on data that is already visible to the public or produced by routine,
non-invasive observation pipelines.

## Why Repetition Matters
Long-term stability requires repeatable measurement. The project emphasizes
consistent cadence and unchanged semantics so that comparisons across months or
years remain meaningful. Repetition reduces noise, helps identify structural
changes, and supports cautious, evidence-based interpretation.

## Limitations
- **No active verification**: Passive observation can miss issues that require
  direct probing to confirm.
- **Signal ambiguity**: Public signals can be delayed, incomplete, or biased by
  external factors.
- **Ethical constraints**: The project prioritizes non-interference, which
  constrains what can be measured.

These limits are intentional. The goal is to establish a durable, ethically
sound baseline rather than to maximize coverage through aggressive techniques.

## DNS TTA Stress Index (aggregated)
The `dns-tta-stress-index` observer estimates DNS stress using only aggregate
signals from minimal A/AAAA probe timing outcomes.

### What DNS stress means
Higher stress indicates slower and less stable DNS answers relative to local
historical baselines, combining:
- elevated p95 response latency,
- increased timeout rate,
- reduced success rate,
- increased latency jitter.

### Why PNG charts are rare
A chart is generated only when significance triggers fire (`z` excursion,
hard timeout threshold breach, or same-day multi-country mass event). This keeps
visual artifacts focused on unusual days, not daily noise.

### Privacy constraints
Tracked outputs exclude hostnames, resolver identifiers, IP addresses, and
per-query rows. Local raw samples are stored outside tracked outputs and are
excluded from Git.
