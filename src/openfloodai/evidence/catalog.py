"""The fixed, explicit list of evidence adapters this build knows about.

Per the doc: "Begin with an explicit local list of known adapters." This
catalog is that list -- a plain static tuple, not a scanner or a dynamic
plugin loader. Adding a new adapter means adding one entry here.
"""

from __future__ import annotations

from dataclasses import dataclass

from openfloodai.evidence.contract import PLUGIN_FAMILIES


@dataclass(frozen=True)
class AdapterDescriptor:
    """One known adapter's identity and display metadata, for settings UIs."""

    plugin_id: str
    plugin_family: str
    display_name: str
    description: str
    is_default: bool

    def __post_init__(self) -> None:
        if self.plugin_family not in PLUGIN_FAMILIES:
            raise ValueError(
                f"plugin_family must be one of {sorted(PLUGIN_FAMILIES)}, "
                f"got {self.plugin_family!r}"
            )

    def to_dict(self) -> dict[str, object]:
        return {
            "plugin_id": self.plugin_id,
            "plugin_family": self.plugin_family,
            "display_name": self.display_name,
            "description": self.description,
            "is_default": self.is_default,
        }


KNOWN_ADAPTERS: tuple[AdapterDescriptor, ...] = (
    AdapterDescriptor(
        plugin_id="pixel_change_region_v1",
        plugin_family="observation",
        display_name="Pixel Change (Region)",
        description=(
            "Compares a site's configured watched region across two frames to "
            "measure raw pixel change. The current default Observation signal."
        ),
        is_default=True,
    ),
)


def known_adapter_ids() -> frozenset[str]:
    return frozenset(adapter.plugin_id for adapter in KNOWN_ADAPTERS)


def default_enabled_by_id() -> dict[str, bool]:
    """Each known adapter's out-of-the-box enabled state, before any override."""

    return {adapter.plugin_id: adapter.is_default for adapter in KNOWN_ADAPTERS}
