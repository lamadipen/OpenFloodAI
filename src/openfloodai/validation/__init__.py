"""Local validation runners for OpenFloodAI."""

from openfloodai.validation.site_setup import (
    ValidationSiteSetupResult,
    setup_validation_site,
)
from openfloodai.validation.site_status import (
    ValidationSiteStatus,
    discover_validation_site_statuses,
    read_validation_site_status,
)

def run_site_validation(*args, **kwargs):
    from openfloodai.validation.site_runner import run_site_validation as _run
    return _run(*args, **kwargs)

def render_site_validation_report(*args, **kwargs):
    from openfloodai.validation.site_runner import render_site_validation_report as _render
    return _render(*args, **kwargs)

__all__ = [
    "ValidationSiteStatus",
    "ValidationSiteSetupResult",
    "discover_validation_site_statuses",
    "read_validation_site_status",
    "run_site_validation",
    "render_site_validation_report",
    "setup_validation_site",
]
