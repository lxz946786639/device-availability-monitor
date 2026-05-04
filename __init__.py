"""Set up the Device Availability Monitor integration."""

from __future__ import annotations

from functools import partial
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.helpers import entity_registry as er

from .const import DOMAIN, PLATFORMS, SERVICE_RESET_STATS, get_display_name
from .coordinator import DeviceAvailabilityMonitorCoordinator

_LEGACY_SENSOR_KEYS: tuple[str, ...] = ("unavailable_device_count",)


async def async_setup(hass: HomeAssistant, config: dict[str, Any]) -> bool:
    """Set up the integration from YAML."""
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up the integration from a config entry."""
    display_name = get_display_name(hass.config.language)
    if entry.title != display_name:
        hass.config_entries.async_update_entry(entry, title=display_name)

    await _async_remove_legacy_entities(hass, entry)

    coordinator = DeviceAvailabilityMonitorCoordinator(hass, entry)
    await coordinator.async_initialize()

    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = coordinator
    entry.async_on_unload(entry.add_update_listener(async_reload_entry))

    if not hass.services.has_service(DOMAIN, SERVICE_RESET_STATS):
        hass.services.async_register(
            DOMAIN,
            SERVICE_RESET_STATS,
            partial(_async_handle_reset_stats, hass),
        )

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if not unload_ok:
        return False

    coordinator: DeviceAvailabilityMonitorCoordinator = hass.data[DOMAIN].pop(entry.entry_id)
    await coordinator.async_shutdown()

    if not hass.data[DOMAIN]:
        hass.data.pop(DOMAIN)
        if hass.services.has_service(DOMAIN, SERVICE_RESET_STATS):
            hass.services.async_remove(DOMAIN, SERVICE_RESET_STATS)

    return True


async def async_reload_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Reload a config entry after options changed."""
    await hass.config_entries.async_reload(entry.entry_id)


async def _async_handle_reset_stats(hass: HomeAssistant, call: ServiceCall) -> None:
    """Handle the reset statistics service."""
    del call
    coordinators: dict[str, DeviceAvailabilityMonitorCoordinator] = hass.data.get(DOMAIN, {})
    for coordinator in coordinators.values():
        await coordinator.async_reset_stats()


async def _async_remove_legacy_entities(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Remove entities that were retired from the integration."""
    entity_registry = er.async_get(hass)
    legacy_unique_ids = {
        f"{entry.entry_id}_{sensor_key}" for sensor_key in _LEGACY_SENSOR_KEYS
    }

    for registry_entry in er.async_entries_for_config_entry(entity_registry, entry.entry_id):
        if registry_entry.unique_id in legacy_unique_ids:
            entity_registry.async_remove(registry_entry.entity_id)
