# World Observer — Significance Model

## What is a Significance Event?
Most daily measurements are routine and repeat the same long-term patterns. A
**significance event** is a rare deviation from an established baseline that
stands out after conservative filtering. It is not an alert, not a claim, and
not a prediction. It is a neutral marker that something measured differently
than it usually does.

## Design Principles
- **Conservative thresholds**: Events are only generated when deviations are
  uncommon in long-term history.
- **One event per day maximum**: The model limits significance to a single daily
  snapshot to reduce noise and avoid overemphasis.
- **Long-term comparability**: Signals are designed to be stable over years, not
  tuned for short-term excitement.
- **Silence is valid data**: Lack of response is recorded as a normal outcome,
  not a trigger for escalation.
- **Observation, not interpretation**: The model documents deviations without
  assigning causes or intent.

## Observer Coverage Overview
All observers run daily on a fixed cadence. Only some observers are eligible to
trigger significance snapshots, and each observer contributes exactly **one**
special signal used for significance evaluation. This keeps the model focused
and prevents overfitting or narrative drift.

## Significance Rules
The table below lists the 15 observers, the single signal each contributes, and
how a significance deviation is defined. The wording is neutral by design and
avoids alert framing.

| Observer | What is monitored | What constitutes a significance deviation |
| --- | --- | --- |
| `area51-reachability` | Daily aggregated outcomes for reachability, DNS status, traceroute stop zones, and public flight counts in the region. | The combined daily summary shifts outside its long-term baseline range for this observer. |
| `asn-visibility-by-country` | Country-level ratio of ASNs with successful TCP 443 reachability. | A country’s visibility ratio is unusually low compared with its historical baseline. |
| `cuba-internet-weather` | Daily classification across targets (clear, unstable, degraded, offline). | The daily classification distribution materially shifts from the long-term pattern. |
| `dns-time-to-answer-index` | Average DNS A/AAAA query time and timeout rate across targets. | Average query time or timeout rate exceeds its long-term baseline range. |
| `global-reachability-score` | Country-level reachability score percent from basic ping/TCP/DNS checks. | A country’s score percent drops well below its established baseline. |
| `internet-shrinkage-index` | Fraction of global targets meeting basic reachability checks. | The index value falls outside its long-term baseline range. |
| `ipv6-adoption-locked-states` | Share of targets with native IPv6 availability (AAAA + IPv6 TCP 443 success). | The share of IPv6-available targets shifts materially from its baseline trend. |
| `iran-dns-behavior` | DNS response status mix and answer counts for selected queries. | The daily mix of answers, timeouts, and refusals departs from historical norms. |
| `mx-presence-by-country` | Country-level presence of MX records from passive sources (placeholder until sources are approved). | A future passive MX presence signal deviates from its long-term baseline once populated. |
| `north-korea-connectivity` | Success rate of basic ping/TCP/DNS checks across selected targets. | The success rate moves outside its long-term baseline range. |
| `silent-countries-list` | Count of countries with no successful basic signals in the daily run. | The number of silent countries is unusually high compared with its baseline. |
| `tls-fingerprint-change` | Count of TLS certificate fingerprint changes among configured targets. | The number of fingerprint changes exceeds its long-term baseline range. |
| `traceroute-to-nowhere` | Typical hop count reached and termination categories (without hop details). | The distribution of hop counts or termination categories shifts from baseline. |
| `undersea-cable-dependency` | Daily reachability checks for targets in countries with higher structural cable dependency. | The reachability outcomes change materially versus the observer’s baseline. |
| `world-observer-meta` | Daily completeness of observer outputs and high-level highlights. | The count of missing observer outputs is unusually high for the day. |

## Regional Origin Context
Raw IP addresses are never shown. Instead, origins are recorded only at a coarse
level, using one of three categories:

- **domestic network**
- **international transit**
- **unknown**

This approach avoids the false precision and privacy risks of GeoIP. Commercial
GeoIP databases can be incomplete, inaccurate, or misleading—especially during
rapid network changes—so the project avoids geographic attribution that could
encourage misinterpretation.

## What This Project Does NOT Do
- No hacking
- No circumvention
- No exploitation
- No surveillance
- No attribution claims
- No political conclusions

## Interpreting Significance Snapshots
A significance snapshot documents a deviation, not a cause. Interpretation
requires external context such as public service announcements, operator status
pages, or independent research. Readers are encouraged to consult primary
sources before drawing conclusions.

## Ethical & Legal Considerations
All data is derived from public, passive measurements. The project stores no
personal data and does not access private infrastructure. The model is designed
to minimize harm, reduce speculation, and maintain a conservative record of
observable deviations.

## Closing Statement
Significance snapshots exist to support long-term archival analysis, not daily
headline narratives. Restraint is an explicit design choice that protects both
accuracy and ethics. The project invites careful, responsible use by
journalists, researchers, and the public.
