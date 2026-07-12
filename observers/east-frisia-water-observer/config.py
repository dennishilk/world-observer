"""Configuration and official source research for East Frisia Water Observer."""
from __future__ import annotations

from models import SourceResearch

OBSERVER = "east-frisia-water-observer"
OBSERVER_NAME = "East Frisia Water Observer"
CATEGORY = "Environment"
REGION = "East Frisia, Lower Saxony, Germany"
LIVE_ADAPTERS_ENABLED = True
MAX_RETRIES = 1

DWD_CONFIG = {
    "station_id": "05640",
    "station_name": "Wittmundhafen",
    "station_latitude": 53.5478,
    "station_longitude": 7.6672,
    "station_state": "Niedersachsen",
    "station_selection_reason": "Fixed DWD CDC recent daily KL station selected as an active official inland/central East Frisia rainfall proxy; Wittmundhafen is a mainland station near Wittmund, closer to the inland East Frisia water-observer area than island/coastal alternatives such as Norderney.",
    "base_url": "https://opendata.dwd.de/climate_environment/CDC/observations_germany/climate/daily/kl/recent/",
    "timeout_seconds": 20,
    "max_retries": 1,
    "min_coverage_7d": 7,
    "min_coverage_30d": 27,
}

WSV_CONFIG = {
    "base_url": "https://www.pegelonline.wsv.de/webservices/rest-api/v2",
    "station_uuid": "abb23dad-0880-41ab-8d2d-dd33e11f148f",
    "station_number": "3910010",
    "station_short_name": "LEERORT",
    "timeseries_shortname": "W",
    "expected_units": {"cm"},
    "timeout_seconds": 10,
    "max_retries": 1,
    "freshness_threshold_minutes": 90,
    "trend_window_minutes": 180,
    "trend_minimum_values": 4,
    "stable_threshold_by_unit": {"cm": 2.0},
}

NLWKN_CONFIG = {
    "base_url": "https://bis.azure-api.net/PegelonlinePublic/REST",
    "public_key": "9dc05f4e3b4a43a9988d747825b39f43",
    "station_id": "184",
    "station_name": "Bensersiel",
    "station_search_terms": ["Bensersiel", "Norden", "Norddeich", "Aurich", "Emden", "Wittmund"],
    "station_type": "Tideaußenpegel",
    "water_body": "Nordsee",
    "operator": "NLWKN Betriebsstelle Aurich",
    "station_code": "9303",
    "parameter_id": "1",
    "parameter_name": "Wasserstand",
    "pinned_datenspur_id": "144222103",
    "pinned_datenspur_identity": {
        "WebDisplayName": "Wasserstand",
        "IstWasserstand": True,
        "IstTide": False,
        "HatPegelstaende": True,
    },
    "unit": "cm",
    "expected_units": {"cm"},
    "recent_days": "-1",
    "timeout_seconds": 10,
    "max_retries": 1,
    "freshness_threshold_minutes": 90,
    "future_clock_skew_tolerance_minutes": 5,
    "trend_window_minutes": 180,
    "trend_minimum_values": 4,
    "stable_threshold_by_unit": {"cm": 2.0},
    "debug_raw_diagnostics": False,
}

SOURCES: dict[str, SourceResearch] = {
    "dwd": SourceResearch(
        agency="Deutscher Wetterdienst (DWD)",
        official_url="https://opendata.dwd.de/climate_environment/CDC/observations_germany/",
        available_datasets=[
            "CDC station observations for precipitation, air temperature, wind, humidity, pressure, sunshine, and other climate elements",
            "Recent and historical daily, hourly, and sub-hourly station files with station metadata",
            "Gridded climate products relevant to hydrological context, where available",
        ],
        update_frequency="Dataset-specific; recent station observation directories are updated operationally, while historical CDC archives are maintained for long-term climate records.",
        access_method="Official DWD CDC Open Data HTTPS file tree and metadata; no scraping or third-party wrappers.",
        expected_usefulness="Best first meteorological context source for rainfall, drought, evapotranspiration proxies, storm events, and data-quality-aware regional water interpretation.",
        licensing="DWD Open Data under GeoNutzV / Datenlizenz Deutschland attribution terms as documented by DWD open-data notices.",
        long_term_stability="High: statutory national meteorological service, official CDC archive, stable HTTPS Open Data structure already used by Wiesmoor Peatland Observer.",
    ),
    "nlwkn": SourceResearch(
        agency="Niedersächsischer Landesbetrieb für Wasserwirtschaft, Küsten- und Naturschutz (NLWKN)",
        official_url="https://www.pegelonline.nlwkn.niedersachsen.de/pdf/BenutzerhandbuchWebservicePegelonline.pdf",
        available_datasets=[
            "Official NLWKN station master data via JSON endpoint /stammdaten/stationen/All",
            "Current unchecked/raw water-level values embedded in station metadata for NLWKN-operated inland and tidal gauges",
            "Recent unchecked/raw water-level time series up to 30 days back via /station/{id}/datenspuren/parameter/{parameter}/tage/{days}",
            "Published warning-stage thresholds on station pages where explicitly defined; not converted into observer classifications",
            "Groundwater portal exists separately, but no equally stable documented machine-readable groundwater API was confirmed for this adapter",
        ],
        update_frequency="Operational raw gauge data; the selected tide gauge is published with minute-level public timestamps, while the documented service allows recent data up to 30 days back.",
        access_method="Official NLWKN Pegelonline public REST JSON service on bis.azure-api.net with the public key documented in NLWKN examples; no HTML scraping, browser automation, wrappers, or WSV endpoints.",
        expected_usefulness="Direct Lower Saxony source for East Frisia NLWKN-operated gauges, especially coastal and local state gauges not covered by the existing WSV adapter.",
        licensing="NLWKN documentation says the webservice can be used free of charge, but www.pegelonline.nlwkn.niedersachsen.de must always be cited; raw values are unchecked and no warranty/availability claim is made.",
        long_term_stability="Medium-high: official state water-management service with PDF documentation dated 2023-10-26, but it uses an Azure API gateway and public key parameter, so failures must remain isolated.",
    ),
    "wsv": SourceResearch(
        agency="Wasserstraßen- und Schifffahrtsverwaltung des Bundes (WSV)",
        official_url="https://www.pegelonline.wsv.de/webservices/rest-api/v2",
        available_datasets=[
            "PEGELONLINE federal waterway station metadata",
            "Current water levels and time series for federal waterways",
            "Related hydrological parameters such as discharge or water temperature where station time series provide them",
        ],
        update_frequency="Near real-time; WSV PEGELONLINE public descriptions indicate minute-current data with station/time-series-specific cadences.",
        access_method="Official WSV PEGELONLINE REST API v2 JSON resources; no SOAP, MQTT, unofficial APIs, scraping, wrappers, visualisation endpoints, or mirrors.",
        expected_usefulness="Useful for Ems and federal-waterway context around East Frisia, navigation-relevant water levels, and cross-checking nearby federal gauges.",
        licensing="Official Open Data records identify PEGELONLINE data as free public data; confirm current DL-DE terms in source metadata before live integration.",
        long_term_stability="High: federal waterway administration service, official REST API documentation, broad reuse through government Open Data catalogues.",
    ),
    "bsh": SourceResearch(
        agency="Bundesamt für Seeschifffahrt und Hydrographie (BSH)",
        official_url="https://www.bsh.de/EN/TOPICS/Geoinformation_and_Open_Data/geoinformation_and_open_data_node.html",
        available_datasets=[
            "BSH geoinformation and marine Open Data services via GeoSeaPortal/GDI-BSH",
            "Oceanographic data including sea-level, tide, hydrographic, and coastal/marine datasets where published",
            "North Sea and German coastal reference datasets relevant to storm-surge and tidal context",
        ],
        update_frequency="Dataset-specific; operational marine products and archived oceanographic datasets are published through BSH data and geodata portals.",
        access_method="Official BSH Open Data, GeoSeaPortal, and OGC/geodata services; no website scraping.",
        expected_usefulness="Important second-phase source for coastal North Sea, tidal, storm-surge, and marine context affecting East Frisia.",
        licensing="BSH states many data are available publicly free of charge and licensed for subsequent use; capture per-dataset licence before downloads.",
        long_term_stability="High: federal maritime and hydrographic agency with established GeoSeaPortal and German Oceanographic Data Center responsibilities.",
    ),
}
