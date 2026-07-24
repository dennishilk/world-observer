# Time Observer data contract

The public Time Observer is implemented in the separate `dennishilk.github.io`
repository. This repository publishes its static scientific-context input as
`world-observer/dashboard/latest/time-observer.json` via the normal dashboard
export and publish helper. The website must not use this file as a clock source.

## Sources and collection policy

`observers/time-observer/observer.py` reads two documented machine-readable
IERS files once per daily World Observer run:

- `finals2000A.all` for UT1−UTC. Its UT1 quality flag is exported as
  `observed` or `predicted`; no prediction is presented as an observation.
- `Leap_Second.dat` / Bulletin C for the TAI−UTC effective-date history.

The output also carries URLs for BIPM, NIST, PTB, and IETF RFC 5905 as
first-party explanatory provenance. They are not scraped. This keeps the
collector small, reproducible, and free of visitor-time API dependencies.

IERS publication and redistribution terms must be rechecked before any use
beyond the compact attributable snapshot exported here. If either source cannot
be read or parsed, its value is `null` and its classification is
`data_unavailable`; the collector never substitutes an estimated DUT1 value.

## Stable frontend fields

The payload contains `generated_at_utc`, `time_scales.tai_minus_utc_seconds`,
`earth_orientation.ut1_minus_utc_seconds`, `earth_orientation.value_date`,
`earth_orientation.status`, `earth_orientation.age_days`, `leap_seconds`, and
`provenance`. Values are populated only after successful source collection;
this document intentionally does not embed a purported current UT1−UTC value.

`status` is one of `observed`, `predicted`, `recent_authoritative_data`, or
`data_unavailable`. A website should display `DATA UNAVAILABLE` for null values
and show the value date, status, and generated timestamp next to UT1−UTC.
