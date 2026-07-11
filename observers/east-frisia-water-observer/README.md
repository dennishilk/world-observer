# East Frisia Water Observer

Environment-category observer for water-related public-data signals in East Frisia, Lower Saxony, Germany.

**Regional public-data observation — not an in-situ sensor network and not a flood-warning service.** Current WSV values are unchecked/raw official measurements and must not be interpreted as universal normal, low, high, dangerous, or as a public warning.

## Current implementation

WSV / PEGELONLINE is the first live water-level source. DWD CDC recent daily KL precipitation is the second live source and is clearly emitted as an inland/central East Frisia rainfall proxy. The remaining NLWKN and BSH adapters intentionally remain `adapter_pending` until separately integrated.

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
- **DWD**: live official DWD CDC recent daily KL precipitation adapter for fixed station `05640` (**Wittmundhafen**) as an inland/central East Frisia rainfall proxy; no scraping and no API key.
- **BSH**: coastal/marine context source, still `adapter_pending`.

PEGELONLINE must not be described as an NLWKN service in this observer.


## Selected DWD CDC daily KL station

Production DWD precipitation is pinned to station `05640` (**Wittmundhafen**) in the official CDC recent daily climate (`KL`) product. It is used only as an **inland/central East Frisia rainfall proxy**: meteorological context for the observer region, not an in-situ water-level measurement and not a warning product. Daily precipitation uses `RSK` in millimetres; DWD missing markers such as `-999` remain unavailable, while valid `0.0` mm remains a real rainfall value. Seven-day totals require 7/7 valid days, and thirty-day totals require at least 27/30 valid days.

### DWD station candidate investigation

The fixed station was revised before merge because `03631` (**Norderney**) is an island/coastal station and should not be presented as a general inland East Frisia proxy. Candidate checks used the official DWD CDC recent daily KL directory and station-list context; no runtime fallback station is implemented.

| Candidate | Station ID | Setting | Recent KL coverage observed | Decision |
|---|---:|---|---|---|
| Aurich | `00243` | Inland / central East Frisia target area | Not suitable for recent KL integration; public station summaries show historical daily coverage ending before the recent period. | Rejected despite ideal geography because the observer requires official recent daily KL data. |
| Emden | `05839` | Mainland East Frisia, western/port/coastal influence | Official recent KL ZIP present. | Considered suitable, but somewhat more maritime/urban-port influenced and farther west than the central observer area. |
| Wittmundhafen | `05640` | Mainland station near Wittmund, inland/central East Frisia | Official recent KL ZIP present. | **Selected** because it is active in recent KL, mainland, and geographically more representative of inland/central East Frisia than island/coastal Norderney. |
| Norderney | `03631` | East Frisian Island / exposed North Sea coast | Official recent KL ZIP present. | Rejected as default because island/coastal rainfall can diverge from inland East Frisia; keep only as a possible explicitly coastal proxy if no mainland station is viable. |

Wittmundhafen is therefore a better fixed proxy for the current observer scope than Norderney: it remains in the official DWD recent daily KL source, avoids island exposure, and sits on the mainland near the central/northeastern East Frisia area requested for this adapter.
