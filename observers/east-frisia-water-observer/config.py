"""Configuration and official source research for East Frisia Water Observer."""
from __future__ import annotations

from models import SourceResearch

OBSERVER = "east-frisia-water-observer"
OBSERVER_NAME = "East Frisia Water Observer"
CATEGORY = "Environment"
REGION = "East Frisia, Lower Saxony, Germany"
LIVE_ADAPTERS_ENABLED = False
MAX_RETRIES = 0

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
        official_url="https://www.pegelonline.nlwkn.niedersachsen.de/",
        available_datasets=[
            "Lower Saxony inland and coastal gauge station master data",
            "Current water levels and hydrological measurements exposed by NLWKN Pegelonline REST webservice",
            "Warning-level context for Niedersachsen gauges where published",
        ],
        update_frequency="Operational gauge data; station-specific cadence may vary from minutes to longer intervals, with public service documentation maintained by NLWKN.",
        access_method="Official NLWKN Pegelonline REST webservice and published user manual; no HTML scraping.",
        expected_usefulness="Most directly useful Lower Saxony source for East Frisia inland waters, coastal gauges, local flood context, and station-level status.",
        licensing="Public, cost-free webservice use according to NLWKN Pegelonline documentation; exact attribution/licence text must be captured before enabling live downloads.",
        long_term_stability="High: state water-management authority service for official Niedersachsen hydrological data.",
    ),
    "wsv": SourceResearch(
        agency="Wasserstraßen- und Schifffahrtsverwaltung des Bundes (WSV)",
        official_url="https://pegelonline.wsv.de/webservice/dokuRestapi",
        available_datasets=[
            "PEGELONLINE federal waterway station metadata",
            "Current water levels and time series for federal waterways",
            "Related hydrological parameters such as discharge or water temperature where station time series provide them",
        ],
        update_frequency="Near real-time; WSV PEGELONLINE public descriptions indicate minute-current data with station/time-series-specific cadences.",
        access_method="Official PEGELONLINE REST API and official Open Data metadata; no unofficial APIs, scraping, or wrappers.",
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
