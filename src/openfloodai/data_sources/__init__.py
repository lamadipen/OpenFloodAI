"""External data source integrations for OpenFloodAI."""

from openfloodai.data_sources.dhm_nepal import (
    DHMNepalError,
    assess_dhm_flood_risk,
    fetch_flood_bulletin,
    summarize_bulletin,
)
from openfloodai.data_sources.nasa_eonet import (
    NASAEONETError,
    fetch_events_near,
    fetch_flood_events,
    summarize_events,
)
from openfloodai.data_sources.nws_alerts import (
    NWSAlertError,
    fetch_active_flood_alerts,
    summarize_alerts,
)
from openfloodai.data_sources.open_meteo import (
    OpenMeteoError,
    assess_precipitation_risk,
    fetch_precipitation,
)
from openfloodai.data_sources.reliefweb import (
    ReliefWebError,
    fetch_active_disasters,
    fetch_flood_reports,
    summarize_reports,
)
from openfloodai.data_sources.usgs_earthquake import (
    USGSEarthquakeError,
    assess_seismic_flood_risk,
    fetch_nearby_earthquakes,
)
from openfloodai.data_sources.usgs_water import (
    USGSDataError,
    compute_flood_proximity,
    fetch_flood_stage,
    fetch_site_conditions,
)

__all__ = [
    "DHMNepalError",
    "NASAEONETError",
    "NWSAlertError",
    "OpenMeteoError",
    "ReliefWebError",
    "USGSDataError",
    "USGSEarthquakeError",
    "assess_dhm_flood_risk",
    "assess_precipitation_risk",
    "assess_seismic_flood_risk",
    "compute_flood_proximity",
    "fetch_active_disasters",
    "fetch_active_flood_alerts",
    "fetch_events_near",
    "fetch_flood_bulletin",
    "fetch_flood_events",
    "fetch_flood_reports",
    "fetch_flood_stage",
    "fetch_nearby_earthquakes",
    "fetch_precipitation",
    "fetch_site_conditions",
    "summarize_alerts",
    "summarize_bulletin",
    "summarize_events",
    "summarize_reports",
]
