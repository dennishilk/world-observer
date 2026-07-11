# East Frisia Water Observer

Environment-category observer for water-related public-data signals in East Frisia, Lower Saxony, Germany.

**Regional public-data observation — not an in-situ sensor network and not a flood-warning service.** Current WSV values are unchecked/raw official measurements and must not be interpreted as universal normal, low, high, dangerous, or as a public warning.

## Current implementation

WSV / PEGELONLINE and NLWKN Pegelonline are separate live water-level sources. DWD CDC recent daily KL precipitation is live and clearly emitted as an inland/central East Frisia rainfall proxy. BSH intentionally remains `adapter_pending` until separately integrated.

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

## NLWKN Pegelonline station validation

The NLWKN adapter is pinned to station ID `184` for **Bensersiel** and parameter ID `1` for water level. A live worldnode test showed that the official metadata endpoint responds but did not include station ID `184`, so the adapter now fails closed when the pinned station is missing instead of selecting another station from search-term matches.

The live adapter uses only the documented official **NLWKN Pegelonline public REST** JSON service described in `Pegelonline Webservice - Benutzerhandbuch` dated 2023-10-26:

- Base: `https://bis.azure-api.net/PegelonlinePublic/REST`
- Station metadata/current values: `/stammdaten/stationen/All?key=...`
- Recent measurements after pinned-station validation: `/station/184/datenspuren/parameter/1/tage/-1?key=...`
- Format: JSON
- Authentication: no per-user account or browser session; the documented public examples include a `key` query parameter.
- Reuse notes: NLWKN says the webservice can be used free of charge, `www.pegelonline.nlwkn.niedersachsen.de` must be cited, raw values are unchecked, and no completeness/correctness/availability warranty is made.

The adapter fails closed unless station `184` and parameter `1` validate against the pinned official metadata. It logs the raw measurement timestamp string exactly as returned before parsing in `diagnostics.raw_measurement_timestamp`, then accepts the confirmed official German local timestamp format `DD.MM.YYYY HH:MM` interpreted with `Europe/Berlin` zoneinfo rules, plus Microsoft JSON date strings with an explicit numeric offset, for example `/Date(1783786800000+0200)/` where used elsewhere. Parsed timestamps are normalized to UTC for emitted observations. Malformed timestamps, `/Date(...)` values without offsets, duplicate timestamps, non-numeric values, and changed pinned metadata keep the NLWKN adapter unavailable rather than silently dropping records.

| Field | Value |
|---|---|
| Station ID | `184` |
| Station name | `Bensersiel` |
| Type | `Tideaußenpegel` |
| Water body | `Nordsee` |
| Operator | `NLWKN Betriebsstelle Aurich` |
| Code | `9303` |
| Parameter | `1` — Wasserstand |
| Unit | `cm` |
| Freshness threshold | 90 minutes |

### NLWKN candidate investigation

Previous research listed candidate East-Frisia/coastal stations from the public NLWKN Pegelonline portal, but the production adapter does not dynamically choose among them. It only requests recent measurements after the pinned Bensersiel station ID is present in the live station metadata and the station name, water body, operator, parameter ID, and unit still match the configured expectations.

Groundwater was reviewed separately through the NLWKN groundwater portal. The portal documents current groundwater-level data and station pages, but no comparably stable, official, documented machine-readable public API was confirmed for this live adapter, so groundwater remains research-only.

## Adapter separation

- **WSV / PEGELONLINE**: federal WSV service, first live REST API v2 water-level adapter.
- **NLWKN**: separate Lower Saxony water-management source, live through the official NLWKN Pegelonline public REST JSON service; not described with WSV terminology and not queried through WSV endpoints.
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
