# East Frisia Water Observer

Environment-category observer scaffold for water-related signals in East Frisia, Lower Saxony, Germany.

This first version is intentionally research and architecture only. It performs no live downloads, uses no third-party wrappers, and does not scrape websites. Each adapter returns `adapter_pending` with structured diagnostics so later integrations can be enabled conservatively.

## Engineering principles

- Modular adapter architecture with one module per source agency.
- Conservative handling of unavailable data: missing live data is represented as `adapter_pending`, not as zero or normal conditions.
- Official, stable public data sources only.
- Detailed diagnostics: `data_status`, `live_adapters_enabled`, `adapter_errors`, `api_attempts`, and `retries` are emitted at both adapter and observer levels.
- Long-term maintainability: source research is centralized in `config.py`, while adapters own their fetch/parse logic.

## Official source research

| Source | Official URL | Available datasets | Update frequency | Access method | Expected usefulness | Licensing | Long-term stability |
|---|---|---|---|---|---|---|---|
| Deutscher Wetterdienst (DWD) | <https://opendata.dwd.de/climate_environment/CDC/observations_germany/> | CDC station observations for precipitation, temperature, wind, humidity, pressure, sunshine, recent/historical daily/hourly/sub-hourly station files, station metadata, and relevant gridded climate products. | Dataset-specific; recent observations are operational while historical CDC archives are maintained for climate records. | Official DWD CDC Open Data HTTPS file tree and metadata. | First meteorological context source for rainfall, drought, evapotranspiration proxies, storm events, and regional hydrological interpretation. | DWD Open Data under GeoNutzV / Datenlizenz Deutschland attribution terms as documented by DWD open-data notices. | High: national meteorological service and official CDC archive already used by Wiesmoor Peatland Observer. |
| NLWKN | <https://www.pegelonline.nlwkn.niedersachsen.de/> | Lower Saxony inland/coastal gauge station master data, current water levels and hydrological measurements via NLWKN Pegelonline REST webservice, and warning-level context where published. | Operational gauge data; station cadence varies from minutes to longer intervals. | Official NLWKN Pegelonline REST webservice and published user manual. | Most directly useful source for East Frisia inland waters, coastal gauges, local flood context, and station-level status. | Public, cost-free webservice use according to NLWKN documentation; exact attribution/licence text must be captured before live downloads. | High: state water-management authority service for Niedersachsen hydrological data. |
| WSV | <https://pegelonline.wsv.de/webservice/dokuRestapi> | PEGELONLINE federal waterway station metadata, current water levels, time series, and related parameters such as discharge or water temperature where station time series provide them. | Near real-time; public descriptions indicate minute-current data with station/time-series-specific cadence. | Official PEGELONLINE REST API and government Open Data metadata. | Useful for Ems and federal-waterway context, navigation-relevant water levels, and cross-checking nearby federal gauges. | Official Open Data records identify PEGELONLINE data as free public data; confirm current DL-DE terms in source metadata before live integration. | High: federal waterway administration service with official REST API documentation. |
| BSH | <https://www.bsh.de/EN/TOPICS/Geoinformation_and_Open_Data/geoinformation_and_open_data_node.html> | BSH geoinformation and marine Open Data services via GeoSeaPortal/GDI-BSH; oceanographic sea-level, tide, hydrographic, coastal, and marine datasets where published. | Dataset-specific; operational marine products and archived oceanographic datasets are published through BSH data/geodata portals. | Official BSH Open Data, GeoSeaPortal, and OGC/geodata services. | Important second-phase source for North Sea coastal, tidal, storm-surge, and marine context affecting East Frisia. | BSH states many data are public, free of charge, and licensed for subsequent use; capture per-dataset licence before downloads. | High: federal maritime and hydrographic agency with established GeoSeaPortal and oceanographic data responsibilities. |

## Implementation recommendation

Integrate **NLWKN Pegelonline first** because it is the most local official hydrological source for Lower Saxony and directly covers inland and coastal gauges relevant to East Frisia. Integrate DWD second for meteorological context, then add WSV for federal-waterway gauge cross-checks and BSH for North Sea/tide/storm-surge context after station selection is documented.
