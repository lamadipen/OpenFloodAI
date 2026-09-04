"""Local validation runners for OpenFloodAI."""

from __future__ import annotations

from typing import TYPE_CHECKING

from openfloodai.validation.site_setup import (
    ValidationSiteSetupResult,
    setup_validation_site,
)
from openfloodai.validation.site_status import (
    ValidationSiteStatus,
    discover_validation_site_statuses,
    read_validation_site_status,
)

if TYPE_CHECKING:
    from pathlib import Path

    from openfloodai.validation.site_runner import SiteValidationReport


def run_site_validation(
    site_dir: Path,
    *,
    config_path: Path | None = None,
) -> SiteValidationReport:
    from openfloodai.validation.site_runner import run_site_validation as _run

    return _run(site_dir, config_path=config_path)


def render_site_validation_report(report: SiteValidationReport) -> str:
    from openfloodai.validation.site_runner import render_site_validation_report as _render

    return _render(report)


__all__ = [
    "ValidationSiteSetupResult",
    "ValidationSiteStatus",
    "discover_validation_site_statuses",
    "read_validation_site_status",
    "render_site_validation_report",
    "run_site_validation",
    "setup_validation_site",
]
