# cuba-internet-weather

## Purpose
This observer models **"internet weather"** in Cuba by collecting a small set of
repeatable, passive measurements. The metaphor helps describe whether
connectivity feels clear, unstable, degraded, or offline without trying to
explain *why* it behaves that way.

## What it measures
Only three signals are collected for each target:

1) **ICMP ping**
   - Packet loss percentage
   - Min / average / max round-trip time (RTT)
2) **TCP handshake on port 443**
   - Success or failure
   - Connect time in milliseconds
3) **DNS resolution timing**
   - A record lookup time
   - Status: `answer`, `timeout`, `nxdomain`, `noanswer`, or `error`

## Weather classification
The observer summarizes all target results into a simple classification:

- **clear**: loss < 10% AND all TCP handshakes succeed
- **unstable**: loss 10–40% OR TCP results are mixed
- **degraded**: loss > 40% OR average RTT above 300 ms
- **offline**: no successful ping AND no TCP handshakes

These thresholds are intentionally simple and should be interpreted as
point-in-time indicators, not long-term assessments.

## Limitations & uncertainty
- Results are **snapshots** and can change quickly.
- DNS, ping, or TCP might fail independently, so partial failures are expected.
- The observer does not attribute causes or identify censorship mechanisms.
- It does not track individual hosts over time inside the module.

## Ethical boundaries
- **No traceroute**
- **No port scanning beyond 443**
- **No brute force or stress testing**
- **No active probing beyond these minimal checks**

## Files
- `observer.py`: runs the measurements and emits JSON output.
- `targets.json`: list of Cuban targets to measure.
