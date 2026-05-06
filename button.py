"""Button platform for Device Availability Monitor."""

from __future__ import annotations

import logging
from dataclasses import dataclass

from homeassistant.components.button import ButtonEntity, ButtonEntityDescription
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import (
    BUTTON_RESET_DEVICE_STATS,
    DOMAIN,
    MANUFACTURER,
    NAME,
    SERVICE_RESET_STATS,
)
from .coordinator import DeviceAvailabilityMonitorCoordinator

LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True, kw_only=True)
class MonitorButtonDescription(ButtonEntityDescription):
    """Description for monitor buttons."""


RESET_DEVICE_STATS_DESCRIPTION = MonitorButtonDescription(
    key=BUTTON_RESET_DEVICE_STATS,
    name=None,
    translation_key=BUTTON_RESET_DEVICE_STATS,
    icon="mdi:refresh",
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up monitor button entities."""
    coordinator: DeviceAvailabilityMonitorCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities(
        [
            DeviceAvailabilityMonitorResetButton(
                coordinator,
                entry,
                RESET_DEVICE_STATS_DESCRIPTION,
            )
        ]
    )


class DeviceAvailabilityMonitorResetButton(
    CoordinatorEntity[DeviceAvailabilityMonitorCoordinator],
    ButtonEntity,
):
    """Representation of the reset statistics button."""

    _attr_has_entity_name = True
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    entity_description: MonitorButtonDescription

    def __init__(
        self,
        coordinator: DeviceAvailabilityMonitorCoordinator,
        entry: ConfigEntry,
        description: MonitorButtonDescription,
    ) -> None:
        """Initialize the button."""
        super().__init__(coordinator)
        self._entry_id = entry.entry_id
        self.entity_description = description
        self._attr_unique_id = f"{entry.entry_id}_{description.key}"
        self._attr_translation_key = description.translation_key or description.key
        self._attr_icon = description.icon
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name=NAME,
            manufacturer=MANUFACTURER,
            model=NAME,
        )

    async def async_press(self) -> None:
        """Trigger a full reset and rescan through the public service."""
        snapshot = self.coordinator.data or {}
        scan_in_progress = bool(
            snapshot.get(
                "scan_in_progress",
                getattr(self.coordinator, "_scan_in_progress", False),
            )
        )
        LOGGER.warning(
            "Reset Device Stats button pressed for entry %s. "
            "This triggers a full rebuild and may interrupt the current scan "
            "(scan_in_progress=%s).",
            self._entry_id,
            scan_in_progress,
        )
        await self.hass.services.async_call(
            DOMAIN,
            SERVICE_RESET_STATS,
            {},
            blocking=False,
        )
