"""External data source integrations for OpenFloodAI."""

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
from openfloodai.data_sources.usgs_water import (
    USGSDataError,
    compute_flood_proximity,
    fetch_flood_stage,
    fetch_site_conditions,
)

__all__ = [
    "NWSAlertError",
    "OpenMeteoError",
    "USGSDataError",
    "assess_precipitation_risk",
    "compute_flood_proximity",
    "fetch_active_flood_alerts",
    "fetch_flood_stage",
    "fetch_precipitation",
    "fetch_site_conditions",
    "summarize_alerts",
]
