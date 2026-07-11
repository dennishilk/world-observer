# East Frisia Water Observer

Environment-category observer for water-related public-data signals in East Frisia, Lower Saxony, Germany.

**Regional public-data observation — not an in-situ sensor network and not a flood-warning service.** Current WSV values are unchecked/raw official measurements and must not be interpreted as universal normal, low, high, dangerous, or as a public warning.

## Current implementation

WSV / PEGELONLINE is the first live water-level source. The remaining DWD, NLWKN, and BSH adapters intentionally remain `adapter_pending` until separately integrated.

The live adapter uses only the documented official **WSV PEGELONLINE REST API v2** JSON service:

- Base: `https://www.pegelonline.wsv.de/webservices/rest-api/v2`
- Station metadata: `/stations/{uuid}.json?includeTimeseries=true&includeCurrentMeasurement=true`
- Recent measurements: `/stations/{uuid}/W/measurements.json?start={utc}&end={utc}`

It does not use SOAP, MQTT, third-party wrappers, HTML scraping, visualisation endpoints, or unofficial mirrors.

## Selected PEGELONLINE station

Production is pinned to immutable PEGELONLINE UUID `abb23dad-0880-41ab-8d2d-dd33e11f148f` for station **LEERORT**.

| Field | Value |
|---|---|
| UUID | `abb23dad-0880-41ab-8d2d-dd33e11f148f` |
| Station number | `3910010` |
| Short / long name | `LEERORT` / `LEERORT` |
| Water body | `EMS` |
| Agency | `STANDORT EMDEN` |
| Coordinates | 53.215335, 7.426191 |
| Timeseries | `W` — `WASSERSTAND ROHDATEN` |
| Unit | `cm` |
| Equidistance observed in metadata | 1 minute |

### Candidate investigation

The official station resource was queried with timeseries and current measurements. East-Frisia-relevant lower-Ems candidates included:

| Candidate | UUID | Water body | Agency | Coordinates | W timeseries / unit | Reason considered |
|---|---|---|---|---|---|---|
| PAPENBURG | `ec4a598d-773d-44c1-935e-2053b54e45a3` | EMS | STANDORT EMDEN | 53.108191, 7.365595 | `W`, `cm` | Lower Ems station with recent 1-minute water-level measurements; slightly farther inland/south of the East Frisia core. |
| WEENER | `aa6af4e6-a44f-46c4-abf6-449f8a68bab1` | EMS | STANDORT EMDEN | 53.161188, 7.371913 | `W`, `cm` | Lower Ems station with recent 1-minute water-level measurements; relevant, but upstream of Leerort. |
| LEERORT | `abb23dad-0880-41ab-8d2d-dd33e11f148f` | EMS | STANDORT EMDEN | 53.215335, 7.426191 | `W`, `cm` | Selected: geographically meaningful at Leer / lower Ems, inside East Frisia context, active water-level series, recent values, documented unit, and enough recent values for trend calculation. |

LEERORT was selected because it is on the Ems at Leerort in the East Frisia / lower-Ems context, is operated under WSV PEGELONLINE station metadata by `STANDORT EMDEN`, exposes active water-level raw data (`W`) in `cm`, and has recent 1-minute measurements suitable for a conservative short-term trend.

## Freshness and trend policy

- Freshness threshold: 90 minutes.
- Trend window: 180 minutes ending at observer execution time.
- Minimum valid measurements for trend: 4.
- Stability threshold for `cm`: absolute change of 2.0 cm or less is `stable`.

Trend is descriptive only:

- `rising`
- `falling`
- `stable`
- `unavailable`

A single current value is not a trend. Missing or malformed measurements are never converted to zero; an official `0` water-level value remains valid.

## Adapter separation

- **WSV / PEGELONLINE**: federal WSV service, first live REST API v2 water-level adapter.
- **NLWKN**: separate Lower Saxony water-management source, still `adapter_pending`.
- **DWD**: meteorological context source, still `adapter_pending`.
- **BSH**: coastal/marine context source, still `adapter_pending`.

PEGELONLINE must not be described as an NLWKN service in this observer.
