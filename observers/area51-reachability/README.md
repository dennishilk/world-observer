# area51-reachability

## Purpose
This observer exists to contrast the **myth** surrounding Area 51 with the **public
reality** around Groom Lake: the only data we can ethically and legally measure are
boring, repeatable signals that behave like ordinary internet and aviation noise.
If the results look flat, that is the point.

## What this observer measures (only aggregated outcomes)
- **Network reachability**: ICMP ping and a TCP handshake on port 443, recorded as
  boolean outcomes only.
- **DNS behavior**: A/AAAA lookups recorded only as `answer`, `timeout`, or `NXDOMAIN`.
- **Traceroute behavior**: maximum hop reached and a coarse classification for where
  it stops (for example, `public_transit`).
- **Flight activity**: daily **aggregated** ADS-B counts for known civilian charter
  flights commonly called “JANET flights,” plus other visible ADS-B flights in the
  region. No callsigns, routes, timestamps, or aircraft identifiers are kept.

## Ethical and legal boundaries
- We do **not** track individuals.
- We do **not** store sensitive data.
- We do **not** attempt to bypass restrictions.
- We do **not** use or infer classified or private information.

These measurements are intentionally limited to what is publicly visible and
ethically defensible.

## What conclusions cannot be drawn
- This observer **cannot** reveal secret activity.
- It **cannot** confirm military operations or infer classified behavior.
- It **cannot** attribute outages or anomalies to specific causes.

If the outputs remain steady or empty, that is expected and consistent with
routine, public internet and aviation behavior.
