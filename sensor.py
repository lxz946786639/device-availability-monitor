"""Sensor platform for Device Availability Monitor."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from homeassistant.components.sensor import SensorEntity, SensorEntityDescription
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import (
    DOMAIN,
    MANUFACTURER,
    NAME,
    SENSOR_CRITICAL_OFFLINE_DEVICES,
    SENSOR_LOW_BATTERY_DEVICES_LIST,
    SENSOR_UNAVAILABLE_BY_INTEGRATION,
    SENSOR_UNAVAILABLE_DEVICES_LIST,
)
from .coordinator import DeviceAvailabilityMonitorCoordinator


@dataclass(frozen=True, kw_only=True)
class MonitorSensorDescription(SensorEntityDescription):
    """Description for monitor sensors."""


SENSOR_DESCRIPTIONS: tuple[MonitorSensorDescription, ...] = (
    MonitorSensorDescription(
        key=SENSOR_UNAVAILABLE_DEVICES_LIST,
        name=None,
        translation_key=SENSOR_UNAVAILABLE_DEVICES_LIST,
        icon="mdi:format-list-bulleted-square",
    ),
    MonitorSensorDescription(
        key=SENSOR_UNAVAILABLE_BY_INTEGRATION,
        name=None,
        translation_key=SENSOR_UNAVAILABLE_BY_INTEGRATION,
        icon="mdi:chart-donut",
    ),
    MonitorSensorDescription(
        key=SENSOR_CRITICAL_OFFLINE_DEVICES,
        name=None,
        translation_key=SENSOR_CRITICAL_OFFLINE_DEVICES,
        icon="mdi:alert-circle",
    ),
    MonitorSensorDescription(
        key=SENSOR_LOW_BATTERY_DEVICES_LIST,
        name=None,
        translation_key=SENSOR_LOW_BATTERY_DEVICES_LIST,
        icon="mdi:battery-alert",
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up monitor sensor entities."""
    coordinator: DeviceAvailabilityMonitorCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities(
        DeviceAvailabilityMonitorSensor(coordinator, entry, description)
        for description in SENSOR_DESCRIPTIONS
    )


class DeviceAvailabilityMonitorSensor(
    CoordinatorEntity[DeviceAvailabilityMonitorCoordinator],
    SensorEntity,
):
    """Representation of a monitor sensor."""

    _attr_has_entity_name = True
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    entity_description: MonitorSensorDescription

    def __init__(
        self,
        coordinator: DeviceAvailabilityMonitorCoordinator,
        entry: ConfigEntry,
        description: MonitorSensorDescription,
    ) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator)
        self.entity_description = description
        self._attr_unique_id = f"{entry.entry_id}_{description.key}"
        self._attr_translation_key = description.translation_key or description.key
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name=NAME,
            manufacturer=MANUFACTURER,
            model=NAME,
        )

    @property
    def native_value(self) -> int:
        """Return the sensor state."""
        snapshot = self.coordinator.data or {}
        key = self.entity_description.key

        if key == SENSOR_UNAVAILABLE_DEVICES_LIST:
            return int(snapshot.get("unavailable_count", 0))
        if key == SENSOR_UNAVAILABLE_BY_INTEGRATION:
            return int(len(snapshot.get("by_integration", {})))
        if key == SENSOR_CRITICAL_OFFLINE_DEVICES:
            return int(snapshot.get("critical_count", 0))
        if key == SENSOR_LOW_BATTERY_DEVICES_LIST:
            return int(snapshot.get("low_battery_count", 0))

        return 0

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return extra attributes for the sensor."""
        snapshot = self.coordinator.data or {}
        key = self.entity_description.key

        if key == SENSOR_UNAVAILABLE_DEVICES_LIST:
            return {
                "devices": snapshot.get("offline_devices", []),
                "devices_total": snapshot.get("offline_devices_total", 0),
                "critical_count": snapshot.get("critical_count", 0),
                "warning_count": snapshot.get("warning_count", 0),
                "devices_truncated": snapshot.get("offline_devices_truncated", False),
                "scan_in_progress": snapshot.get("scan_in_progress", False),
                "scan_processed_entities": snapshot.get("scan_processed_entities", 0),
                "scan_total_entities": snapshot.get("scan_total_entities", 0),
                "updated_at": snapshot.get("updated_at"),
            }

        if key == SENSOR_UNAVAILABLE_BY_INTEGRATION:
            return {
                "by_integration": snapshot.get("by_integration", {}),
                "scan_in_progress": snapshot.get("scan_in_progress", False),
                "scan_processed_entities": snapshot.get("scan_processed_entities", 0),
                "scan_total_entities": snapshot.get("scan_total_entities", 0),
                "updated_at": snapshot.get("updated_at"),
            }

        if key == SENSOR_LOW_BATTERY_DEVICES_LIST:
            return {
                "devices": snapshot.get("low_battery_devices", []),
                "devices_total": snapshot.get("low_battery_devices_total", 0),
                "devices_truncated": snapshot.get(
                    "low_battery_devices_truncated", False
                ),
                "low_battery_threshold": snapshot.get("low_battery_threshold", 20),
                "treat_battery_unavailable_unknown_as_low": snapshot.get(
                    "treat_battery_unavailable_unknown_as_low", True
                ),
                "scan_in_progress": snapshot.get("scan_in_progress", False),
                "scan_processed_entities": snapshot.get("scan_processed_entities", 0),
                "scan_total_entities": snapshot.get("scan_total_entities", 0),
                "updated_at": snapshot.get("updated_at"),
            }

        return {
            "devices": snapshot.get("critical_devices", []),
            "devices_total": snapshot.get("critical_devices_total", 0),
            "devices_truncated": snapshot.get("critical_devices_truncated", False),
            "scan_in_progress": snapshot.get("scan_in_progress", False),
            "scan_processed_entities": snapshot.get("scan_processed_entities", 0),
            "scan_total_entities": snapshot.get("scan_total_entities", 0),
            "updated_at": snapshot.get("updated_at"),
        }
