"""Coordinator for Device Availability Monitor."""

from __future__ import annotations

import asyncio
import math
from collections import deque
from contextlib import suppress
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from itertools import islice
import logging
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import CALLBACK_TYPE, Event, HomeAssistant, callback, split_entity_id
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.event import async_call_later, async_track_time_interval
from homeassistant.helpers.storage import Store
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator
from homeassistant.util import dt as dt_util

from .const import (
    CONF_CLEANUP_ORPHAN_AFTER_HOURS,
    CONF_CRITICAL_THRESHOLD,
    CONF_EXCLUDE_DEVICES,
    CONF_EXCLUDE_DOMAINS,
    CONF_EXCLUDE_ENTITIES,
    CONF_EXCLUDE_INTEGRATIONS,
    CONF_LOW_BATTERY_THRESHOLD,
    CONF_OFFLINE_STRATEGY,
    CONF_TRACKED_DOMAINS,
    CONF_TREAT_BATTERY_UNAVAILABLE_UNKNOWN_AS_LOW,
    CONF_TREAT_UNKNOWN_AS_OFFLINE,
    CONF_UI_REFRESH_INTERVAL,
    CONF_WARNING_THRESHOLD,
    CORE_OFFLINE_DOMAINS,
    DEFAULT_CLEANUP_ORPHAN_AFTER_HOURS,
    DEFAULT_CRITICAL_THRESHOLD,
    DEFAULT_LOW_BATTERY_THRESHOLD,
    DEFAULT_OFFLINE_STRATEGY,
    DEFAULT_TRACKED_DOMAINS,
    DEFAULT_TREAT_BATTERY_UNAVAILABLE_UNKNOWN_AS_LOW,
    DEFAULT_TREAT_UNKNOWN_AS_OFFLINE,
    DEFAULT_UI_REFRESH_INTERVAL,
    DEFAULT_WARNING_THRESHOLD,
    DOMAIN,
    EVENT_STATE_CHANGED,
    FLAP_THRESHOLD,
    FLAP_WINDOW_SECONDS,
    MAX_EXPOSED_CRITICAL_DEVICES,
    MAX_EXPOSED_OFFLINE_DEVICES,
    MAX_EXPOSED_OFFLINE_ENTITIES_PER_DEVICE,
    MAX_PENDING_EVENTS,
    MAX_FLAP_HISTORY_ENTRIES,
    NAME,
    REGISTRY_REBUILD_DEBOUNCE_SECONDS,
    SEVERITY_CRITICAL,
    SEVERITY_WARNING,
    STORAGE_SAVE_DELAY_SECONDS,
    STORAGE_VERSION,
    UNKNOWN_INTEGRATION,
    get_storage_key,
)

LOGGER = logging.getLogger(__name__)
SCAN_BATCH_SIZE = 500
DEVICE_STATUS_ONLINE = "online"
DEVICE_STATUS_DEGRADED = "degraded"
DEVICE_STATUS_OFFLINE = "offline"


@dataclass(slots=True)
class MonitorConfig:
    """Normalized runtime configuration."""

    warning_threshold: int = DEFAULT_WARNING_THRESHOLD
    critical_threshold: int = DEFAULT_CRITICAL_THRESHOLD
    offline_strategy: str = DEFAULT_OFFLINE_STRATEGY
    treat_unknown_as_offline: bool = DEFAULT_TREAT_UNKNOWN_AS_OFFLINE
    tracked_domains: set[str] = field(default_factory=lambda: set(DEFAULT_TRACKED_DOMAINS))
    exclude_devices: set[str] = field(default_factory=set)
    exclude_entities: set[str] = field(default_factory=set)
    exclude_integrations: set[str] = field(default_factory=set)
    exclude_domains: set[str] = field(default_factory=set)
    ui_refresh_interval: int = DEFAULT_UI_REFRESH_INTERVAL
    cleanup_orphan_after_hours: int = DEFAULT_CLEANUP_ORPHAN_AFTER_HOURS
    low_battery_threshold: int = DEFAULT_LOW_BATTERY_THRESHOLD
    treat_battery_unavailable_unknown_as_low: bool = (
        DEFAULT_TREAT_BATTERY_UNAVAILABLE_UNKNOWN_AS_LOW
    )


@dataclass(slots=True)
class MonitoredEntity:
    """Metadata for a monitored entity."""

    device_id: str
    entity_domain: str
    integration: str
    is_core: bool = False


@dataclass(slots=True)
class DeviceState:
    """Runtime state for a monitored device."""

    device_id: str
    device_name: str
    integration: str = UNKNOWN_INTEGRATION
    entity_ids: set[str] = field(default_factory=set)
    offline_entities: set[str] = field(default_factory=set)
    offline_entity_since: dict[str, datetime] = field(default_factory=dict)
    entity_domains: set[str] = field(default_factory=set)
    battery_entity_values: dict[str, float] = field(default_factory=dict)
    battery_percent: float | None = None
    source_offline_entity_id: str | None = None
    source_battery_entity_id: str | None = None
    offline_since: datetime | None = None
    flap_history: deque[datetime] = field(
        default_factory=lambda: deque(maxlen=MAX_FLAP_HISTORY_ENTRIES)
    )
    flap_count: int = 0
    health_state: str = DEVICE_STATUS_ONLINE
    health_reasons: set[str] = field(default_factory=set)


def config_from_entry(entry: ConfigEntry) -> MonitorConfig:
    """Build runtime config from the config entry."""
    merged: dict[str, Any] = {
        CONF_WARNING_THRESHOLD: DEFAULT_WARNING_THRESHOLD,
        CONF_CRITICAL_THRESHOLD: DEFAULT_CRITICAL_THRESHOLD,
        CONF_OFFLINE_STRATEGY: DEFAULT_OFFLINE_STRATEGY,
        CONF_TREAT_UNKNOWN_AS_OFFLINE: DEFAULT_TREAT_UNKNOWN_AS_OFFLINE,
        CONF_TRACKED_DOMAINS: list(DEFAULT_TRACKED_DOMAINS),
        CONF_EXCLUDE_DEVICES: [],
        CONF_EXCLUDE_ENTITIES: [],
        CONF_EXCLUDE_INTEGRATIONS: [],
        CONF_EXCLUDE_DOMAINS: [],
        CONF_UI_REFRESH_INTERVAL: DEFAULT_UI_REFRESH_INTERVAL,
        CONF_CLEANUP_ORPHAN_AFTER_HOURS: DEFAULT_CLEANUP_ORPHAN_AFTER_HOURS,
        CONF_LOW_BATTERY_THRESHOLD: DEFAULT_LOW_BATTERY_THRESHOLD,
        CONF_TREAT_BATTERY_UNAVAILABLE_UNKNOWN_AS_LOW: (
            DEFAULT_TREAT_BATTERY_UNAVAILABLE_UNKNOWN_AS_LOW
        ),
    }
    merged.update(entry.data)
    merged.update(entry.options)

    return MonitorConfig(
        warning_threshold=int(merged[CONF_WARNING_THRESHOLD]),
        critical_threshold=int(merged[CONF_CRITICAL_THRESHOLD]),
        offline_strategy=str(merged[CONF_OFFLINE_STRATEGY]),
        treat_unknown_as_offline=bool(merged[CONF_TREAT_UNKNOWN_AS_OFFLINE]),
        tracked_domains=set(merged[CONF_TRACKED_DOMAINS]),
        exclude_devices=set(merged[CONF_EXCLUDE_DEVICES]),
        exclude_entities=set(merged[CONF_EXCLUDE_ENTITIES]),
        exclude_integrations=set(merged[CONF_EXCLUDE_INTEGRATIONS]),
        exclude_domains=set(merged[CONF_EXCLUDE_DOMAINS]),
        ui_refresh_interval=int(merged[CONF_UI_REFRESH_INTERVAL]),
        cleanup_orphan_after_hours=int(merged[CONF_CLEANUP_ORPHAN_AFTER_HOURS]),
        low_battery_threshold=int(merged[CONF_LOW_BATTERY_THRESHOLD]),
        treat_battery_unavailable_unknown_as_low=bool(
            merged[CONF_TREAT_BATTERY_UNAVAILABLE_UNKNOWN_AS_LOW]
        ),
    )


def is_entity_offline(state: str | None, treat_unknown_as_offline: bool) -> bool:
    """Return whether an entity state should be treated as offline."""
    if state == "unavailable":
        return True
    if treat_unknown_as_offline and state == "unknown":
        return True
    return False


def _is_core_domain(domain: str) -> bool:
    """Return whether a domain should be treated as a core device domain."""
    return domain in CORE_OFFLINE_DOMAINS


class DeviceAvailabilityMonitorCoordinator(DataUpdateCoordinator[dict[str, Any] | None]):
    """Track unavailable devices and publish snapshot data."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        """Initialize the coordinator."""
        super().__init__(hass, LOGGER, name=NAME)
        self.entry = entry
        self.config = config_from_entry(entry)
        self._store = Store(hass, STORAGE_VERSION, get_storage_key(entry.entry_id))
        self._stored_device_metadata: dict[str, dict[str, Any]] = {}
        self.entity_index: dict[str, MonitoredEntity] = {}
        self.battery_entity_index: dict[str, MonitoredEntity] = {}
        self._device_states: dict[str, DeviceState] = {}
        self.last_recovered_at: dict[str, datetime] = {}

        self._unsub_state_listener: CALLBACK_TYPE | None = None
        self._unsub_entity_registry: CALLBACK_TYPE | None = None
        self._unsub_device_registry: CALLBACK_TYPE | None = None
        self._unsub_registry_rebuild: CALLBACK_TYPE | None = None
        self._unsub_refresh_timer: CALLBACK_TYPE | None = None

        self._scan_version = 0
        self._current_scan_task: asyncio.Task[None] | None = None
        self._scan_in_progress = False
        self._scan_processed_entities = 0
        self._scan_total_entities = 0
        self._pending_entity_refreshes: dict[str, tuple[datetime, Any | None]] = {}

        self._offline_devices: list[dict[str, Any]] = []
        self._offline_device_index: dict[str, int] = {}
        self._critical_devices: list[dict[str, Any]] = []
        self._critical_device_index: dict[str, int] = {}
        self._degraded_devices: list[dict[str, Any]] = []
        self._degraded_device_index: dict[str, int] = {}
        self._low_battery_devices: list[dict[str, Any]] = []
        self._low_battery_device_index: dict[str, int] = {}
        self._flapping_devices: list[dict[str, Any]] = []
        self._flapping_device_index: dict[str, int] = {}
        self._by_integration: dict[str, int] = {}
        self._offline_warning_count = 0

        self._snapshot_static: dict[str, Any] = {
            "offline_devices": self._offline_devices,
            "critical_devices": self._critical_devices,
            "degraded_devices": self._degraded_devices,
            "low_battery_devices": self._low_battery_devices,
            "flapping_devices": self._flapping_devices,
            "by_integration": self._by_integration,
            "offline_strategy": self.config.offline_strategy,
            "low_battery_threshold": self.config.low_battery_threshold,
            "treat_battery_unavailable_unknown_as_low": (
                self.config.treat_battery_unavailable_unknown_as_low
            ),
            "flap_window_seconds": FLAP_WINDOW_SECONDS,
            "flap_threshold": FLAP_THRESHOLD,
        }
        self._snapshot_dynamic: dict[str, Any] = {
            "unavailable_count": 0,
            "offline_count": 0,
            "critical_count": 0,
            "warning_count": 0,
            "degraded_count": 0,
            "flapping_count": 0,
            "low_battery_count": 0,
            "offline_devices_total": 0,
            "offline_devices_truncated": False,
            "critical_devices_total": 0,
            "critical_devices_truncated": False,
            "degraded_devices_total": 0,
            "degraded_devices_truncated": False,
            "low_battery_devices_total": 0,
            "low_battery_devices_truncated": False,
            "flapping_devices_total": 0,
            "flapping_devices_truncated": False,
            "scan_in_progress": False,
            "scan_processed_entities": 0,
            "scan_total_entities": 0,
            "updated_at": None,
        }
        self._has_complete_snapshot = False

    async def async_initialize(self) -> None:
        """Initialize indexes, snapshot data, and listeners."""
        await self._async_load_storage()
        await self._async_rebuild_indexes(preserve_existing=False)

        self._unsub_entity_registry = self.hass.bus.async_listen(
            er.EVENT_ENTITY_REGISTRY_UPDATED,
            self._async_handle_entity_registry_event,
        )
        self._unsub_device_registry = self.hass.bus.async_listen(
            dr.EVENT_DEVICE_REGISTRY_UPDATED,
            self._async_handle_device_registry_event,
        )

    async def _async_load_storage(self) -> None:
        """Load persisted runtime metadata from storage."""
        try:
            stored = await self._store.async_load()
        except Exception:
            LOGGER.exception("Failed to load Device Availability Monitor storage")
            return

        if not isinstance(stored, dict):
            self._stored_device_metadata = {}
            self.last_recovered_at = {}
            return

        devices = stored.get("devices")
        if isinstance(devices, dict):
            self._stored_device_metadata = {
                device_id: metadata
                for device_id, metadata in devices.items()
                if isinstance(device_id, str) and isinstance(metadata, dict)
            }
        else:
            self._stored_device_metadata = {}

        recovered_at_raw = stored.get("last_recovered_at")
        if isinstance(recovered_at_raw, dict):
            self.last_recovered_at = {
                device_id: parsed
                for device_id, parsed in (
                    (
                        device_id,
                        self._parse_storage_datetime(value),
                    )
                    for device_id, value in recovered_at_raw.items()
                    if isinstance(device_id, str)
                )
                if parsed is not None
            }
        else:
            self.last_recovered_at = {}

        self._restore_persisted_snapshot(stored.get("last_snapshot"))

    def _build_storage_data(self) -> dict[str, Any]:
        """Build the storage payload for the current runtime state."""
        devices: dict[str, dict[str, Any]] = {}
        for device_id, device_state in self._device_states.items():
            device_payload: dict[str, Any] = {}
            if device_state.offline_since is not None:
                device_payload["offline_since"] = self._serialize_datetime(
                    device_state.offline_since
                )
            if device_state.offline_entity_since:
                device_payload["offline_entity_since"] = {
                    entity_id: self._serialize_datetime(since)
                    for entity_id, since in device_state.offline_entity_since.items()
                    if since is not None
                }
            if device_state.flap_history:
                device_payload["flap_history"] = [
                    self._serialize_datetime(occurred_at)
                    for occurred_at in device_state.flap_history
                ]
            if device_payload:
                devices[device_id] = device_payload

        recovered_at = {
            device_id: self._serialize_datetime(value)
            for device_id, value in self.last_recovered_at.items()
            if value is not None
        }

        payload: dict[str, Any] = {
            "devices": devices,
            "last_recovered_at": recovered_at,
        }
        last_snapshot = self._build_persisted_snapshot()
        if last_snapshot is not None:
            payload["last_snapshot"] = last_snapshot
        return payload

    def _build_persisted_snapshot(self) -> dict[str, Any] | None:
        """Build the last complete public snapshot for startup restoration."""
        if not self._has_complete_snapshot:
            return None

        return {
            "offline_devices": [dict(item) for item in self._offline_devices],
            "critical_devices": [dict(item) for item in self._critical_devices],
            "degraded_devices": [dict(item) for item in self._degraded_devices],
            "low_battery_devices": [dict(item) for item in self._low_battery_devices],
            "flapping_devices": [dict(item) for item in self._flapping_devices],
            "by_integration": dict(self._by_integration),
            "offline_warning_count": self._offline_warning_count,
            "updated_at": self._snapshot_dynamic.get("updated_at"),
        }

    def _restore_persisted_snapshot(self, snapshot: Any) -> None:
        """Restore the last complete public snapshot from storage."""
        if not isinstance(snapshot, dict):
            return

        self._restore_snapshot_bucket(
            self._offline_devices,
            self._offline_device_index,
            snapshot.get("offline_devices"),
        )
        self._restore_snapshot_bucket(
            self._critical_devices,
            self._critical_device_index,
            snapshot.get("critical_devices"),
        )
        self._restore_snapshot_bucket(
            self._degraded_devices,
            self._degraded_device_index,
            snapshot.get("degraded_devices"),
        )
        self._restore_snapshot_bucket(
            self._low_battery_devices,
            self._low_battery_device_index,
            snapshot.get("low_battery_devices"),
        )
        self._restore_snapshot_bucket(
            self._flapping_devices,
            self._flapping_device_index,
            snapshot.get("flapping_devices"),
        )

        self._by_integration.clear()
        by_integration = snapshot.get("by_integration")
        if isinstance(by_integration, dict):
            for integration, count in by_integration.items():
                if not isinstance(integration, str):
                    continue
                try:
                    count_int = int(count)
                except (TypeError, ValueError):
                    continue
                if count_int > 0:
                    self._by_integration[integration] = count_int

        warning_count = snapshot.get("offline_warning_count")
        try:
            self._offline_warning_count = int(warning_count)
        except (TypeError, ValueError):
            self._offline_warning_count = sum(
                1
                for device in self._offline_devices
                if device.get("severity") == SEVERITY_WARNING
            )

        updated_at = snapshot.get("updated_at")
        if isinstance(updated_at, str):
            self._snapshot_dynamic["updated_at"] = updated_at

        self._has_complete_snapshot = True

    @staticmethod
    def _restore_snapshot_bucket(
        bucket: list[dict[str, Any]],
        index: dict[str, int],
        raw_items: Any,
    ) -> None:
        """Restore one persisted snapshot bucket and its index."""
        bucket.clear()
        index.clear()
        if not isinstance(raw_items, list):
            return

        for raw_item in raw_items:
            if not isinstance(raw_item, dict):
                continue
            device_id = raw_item.get("device_id")
            if not isinstance(device_id, str) or device_id in index:
                continue
            index[device_id] = len(bucket)
            bucket.append(dict(raw_item))

    def _request_storage_save(self) -> None:
        """Schedule a debounced storage write."""
        self._store.async_delay_save(self._build_storage_data, STORAGE_SAVE_DELAY_SECONDS)

    @staticmethod
    def _serialize_datetime(value: datetime | None) -> str | None:
        """Serialize a timezone-aware datetime for storage."""
        if value is None:
            return None
        return dt_util.as_utc(value).isoformat()

    @staticmethod
    def _parse_storage_datetime(value: Any) -> datetime | None:
        """Parse a stored datetime string."""
        if not isinstance(value, str):
            return None

        parsed = dt_util.parse_datetime(value)
        if parsed is None:
            return None
        return dt_util.as_utc(parsed)

    def _apply_persisted_device_metadata(
        self, device_state: DeviceState, persisted: dict[str, Any]
    ) -> None:
        """Restore per-device runtime metadata from storage."""
        offline_since = self._parse_storage_datetime(persisted.get("offline_since"))
        if offline_since is not None:
            device_state.offline_since = offline_since

        offline_entity_since_raw = persisted.get("offline_entity_since")
        if isinstance(offline_entity_since_raw, dict):
            device_state.offline_entity_since = {
                entity_id: since
                for entity_id, since in (
                    (
                        entity_id,
                        self._parse_storage_datetime(value),
                    )
                    for entity_id, value in offline_entity_since_raw.items()
                    if isinstance(entity_id, str)
                )
                if since is not None and entity_id in device_state.entity_ids
            }

        flap_history_raw = persisted.get("flap_history")
        if isinstance(flap_history_raw, list):
            parsed_history = [
                occurred_at
                for occurred_at in (
                    self._parse_storage_datetime(value) for value in flap_history_raw
                )
                if occurred_at is not None
            ]
            device_state.flap_history = deque(
                parsed_history,
                maxlen=MAX_FLAP_HISTORY_ENTRIES,
            )
            self._trim_flap_history(device_state, dt_util.utcnow())
        else:
            device_state.flap_history = deque(maxlen=MAX_FLAP_HISTORY_ENTRIES)
            device_state.flap_count = 0

        last_recovered_at = self._parse_storage_datetime(persisted.get("last_recovered_at"))
        if last_recovered_at is not None:
            self.last_recovered_at[device_state.device_id] = last_recovered_at

    def _copy_device_runtime_state(
        self, target: DeviceState, source: DeviceState
    ) -> None:
        """Copy runtime-only state between device state instances."""
        target.offline_entities = set(source.offline_entities)
        target.offline_entity_since = dict(source.offline_entity_since)
        target.entity_domains = set(source.entity_domains)
        target.battery_entity_values = dict(source.battery_entity_values)
        target.battery_percent = source.battery_percent
        target.source_offline_entity_id = source.source_offline_entity_id
        target.source_battery_entity_id = source.source_battery_entity_id
        target.offline_since = source.offline_since
        target.flap_history = deque(source.flap_history, maxlen=MAX_FLAP_HISTORY_ENTRIES)
        target.flap_count = source.flap_count
        target.health_state = source.health_state
        target.health_reasons = set(source.health_reasons)

    async def async_shutdown(self) -> None:
        """Tear down listeners."""
        if self._unsub_state_listener is not None:
            self._unsub_state_listener()
            self._unsub_state_listener = None
        if self._unsub_entity_registry is not None:
            self._unsub_entity_registry()
            self._unsub_entity_registry = None
        if self._unsub_device_registry is not None:
            self._unsub_device_registry()
            self._unsub_device_registry = None
        if self._unsub_registry_rebuild is not None:
            self._unsub_registry_rebuild()
            self._unsub_registry_rebuild = None
        if self._unsub_refresh_timer is not None:
            self._unsub_refresh_timer()
            self._unsub_refresh_timer = None
        if self._current_scan_task is not None:
            self._current_scan_task.cancel()
            with suppress(asyncio.CancelledError):
                try:
                    await self._current_scan_task
                except Exception:
                    LOGGER.exception("Scan task failed during shutdown")
            self._current_scan_task = None
        self._scan_in_progress = False
        self._pending_entity_refreshes.clear()
        self._update_refresh_timer()
        try:
            await self._store.async_save(self._build_storage_data())
        except Exception:
            LOGGER.exception("Failed to save Device Availability Monitor storage during shutdown")

    async def async_reset_stats(self) -> None:
        """Reset runtime state and rebuild the snapshot."""
        LOGGER.info("Resetting Device Availability Monitor statistics")
        self.last_recovered_at.clear()
        self._stored_device_metadata.clear()
        self._pending_entity_refreshes.clear()
        with suppress(Exception):
            await self._store.async_remove()
        self._reset_snapshot_state()
        self._has_complete_snapshot = False
        self.async_set_updated_data(None)
        await self._async_rebuild_indexes(preserve_existing=False)

    async def _async_rebuild_indexes(self, preserve_existing: bool) -> None:
        """Rebuild indexes and launch a new scan."""
        previous_device_states = self._device_states if preserve_existing else None
        (
            self.entity_index,
            self.battery_entity_index,
            self._device_states,
        ) = self._build_indexes(previous_device_states)
        self._scan_total_entities = len(set(self.entity_index) | set(self.battery_entity_index))
        self._scan_processed_entities = 0

        self._async_resubscribe_state_listener()
        await self.start_scan()

    @callback
    def _async_resubscribe_state_listener(self) -> None:
        """Subscribe to state change events for tracked entities."""
        if self._unsub_state_listener is not None:
            self._unsub_state_listener()
            self._unsub_state_listener = None

        if not self.entity_index and not self.battery_entity_index:
            return

        self._unsub_state_listener = self.hass.bus.async_listen(
            EVENT_STATE_CHANGED,
            self._async_handle_state_changed,
        )

    async def start_scan(self) -> None:
        """Cancel any in-flight scan and start a new batched state scan."""
        self._scan_version += 1
        version = self._scan_version
        current_task = asyncio.current_task()

        self._scan_in_progress = True
        self._scan_processed_entities = 0
        self._pending_entity_refreshes.clear()
        # Keep the last complete snapshot visible while the new scan builds a
        # fresh device-state model. This avoids publishing transient zero counts
        # during startup or registry rebuild storms.
        if self._has_complete_snapshot:
            self._publish_snapshot(dt_util.utcnow())

        if (
            self._current_scan_task is not None
            and self._current_scan_task is not current_task
            and not self._current_scan_task.done()
        ):
            self._current_scan_task.cancel()
            with suppress(asyncio.CancelledError):
                try:
                    await self._current_scan_task
                except Exception:
                    LOGGER.exception("Previous scan failed while starting a new scan")

        self._current_scan_task = self.hass.async_create_task(self._scan(version))

    def _build_indexes(
        self,
        previous_device_states: dict[str, DeviceState] | None = None,
    ) -> tuple[
        dict[str, MonitoredEntity],
        dict[str, MonitoredEntity],
        dict[str, DeviceState],
    ]:
        """Build fresh registry-backed indexes."""
        entity_registry = er.async_get(self.hass)
        device_registry = dr.async_get(self.hass)

        entity_index: dict[str, MonitoredEntity] = {}
        battery_entity_index: dict[str, MonitoredEntity] = {}
        device_states: dict[str, DeviceState] = {}
        device_name_cache: dict[str, str] = {}

        for entry in entity_registry.entities.values():
            entity_id = entry.entity_id
            device_id = entry.device_id
            if device_id is None or entry.disabled_by is not None:
                continue

            domain = split_entity_id(entity_id)[0]
            integration = entry.platform or UNKNOWN_INTEGRATION
            tracks_offline = domain in self.config.tracked_domains
            tracks_battery = self._is_battery_entity(entry)

            if not tracks_offline and not tracks_battery:
                continue
            if entity_id in self.config.exclude_entities:
                continue
            if device_id in self.config.exclude_devices:
                continue
            if integration in self.config.exclude_integrations:
                continue
            if tracks_offline and domain in self.config.exclude_domains:
                tracks_offline = False
            if not tracks_offline and not tracks_battery:
                continue

            device_name = device_name_cache.get(device_id)
            if device_name is None:
                device_entry = device_registry.async_get(device_id)
                device_name = self._resolve_device_name(device_entry, entry)
                device_name_cache[device_id] = device_name

            monitored_entity = MonitoredEntity(
                device_id=device_id,
                entity_domain=domain,
                integration=integration,
                is_core=_is_core_domain(domain),
            )
            if tracks_offline:
                entity_index[entity_id] = monitored_entity
            if tracks_battery:
                battery_entity_index[entity_id] = monitored_entity

            device_state = device_states.setdefault(
                device_id,
                DeviceState(
                    device_id=device_id,
                    device_name=device_name,
                    integration=integration,
                ),
            )
            device_state.device_name = device_name
            if device_state.integration == UNKNOWN_INTEGRATION or integration != UNKNOWN_INTEGRATION:
                device_state.integration = integration
            device_state.entity_ids.add(entity_id)

            if previous_device_states is not None:
                previous = previous_device_states.get(device_id)
                if previous is not None:
                    self._copy_device_runtime_state(device_state, previous)

        if previous_device_states is None:
            for device_id, device_state in device_states.items():
                persisted = self._stored_device_metadata.get(device_id)
                if persisted is not None:
                    self._apply_persisted_device_metadata(device_state, persisted)

        return entity_index, battery_entity_index, device_states

    @callback
    def _async_handle_state_changed(self, event: Event) -> None:
        """Handle a monitored entity changing state."""
        entity_id = event.data.get("entity_id")
        if entity_id is None:
            return
        if entity_id not in self.entity_index and entity_id not in self.battery_entity_index:
            return

        if self._scan_in_progress:
            self._pending_entity_refreshes[entity_id] = (
                event.time_fired or dt_util.utcnow(),
                event.data.get("new_state"),
            )
            if len(self._pending_entity_refreshes) == MAX_PENDING_EVENTS:
                LOGGER.debug(
                    "Pending update queue reached advisory limit of %s entities",
                    MAX_PENDING_EVENTS,
                )
            return

        changed = self._apply_entity_current_state(
            entity_id,
            event.time_fired or dt_util.utcnow(),
            record_flap=True,
            state=event.data.get("new_state"),
        )
        if not changed:
            return

        if entity_id in self.entity_index:
            self._cleanup_orphan_metadata(event.time_fired or dt_util.utcnow())
        self._update_refresh_timer()
        self._publish_snapshot(event.time_fired or dt_util.utcnow())

    async def _scan(self, version: int) -> None:
        """Scan current entity states in batches to avoid large startup spikes."""
        scan_started_at = dt_util.utcnow()
        processed = 0

        try:
            entity_ids = iter(set(self.entity_index) | set(self.battery_entity_index))
            while True:
                if version != self._scan_version:
                    return

                batch = list(islice(entity_ids, SCAN_BATCH_SIZE))
                if not batch:
                    break

                for entity_id in batch:
                    if version != self._scan_version:
                        return
                    self._apply_entity_current_state(
                        entity_id,
                        scan_started_at,
                        record_flap=False,
                        sync_snapshot=False,
                    )
                    processed += 1

                self._scan_processed_entities = processed
                if self._has_complete_snapshot:
                    self._publish_snapshot(dt_util.utcnow())
                await asyncio.sleep(0)
                if version != self._scan_version:
                    return

            if version != self._scan_version:
                return
            finished_at = dt_util.utcnow()
            pending_items = tuple(self._pending_entity_refreshes.items())
            self._pending_entity_refreshes.clear()
            for entity_id, (changed_at, state) in sorted(
                pending_items,
                key=lambda item: item[1][0],
            ):
                self._apply_entity_current_state(
                    entity_id,
                    changed_at,
                    record_flap=True,
                    state=state,
                    sync_snapshot=False,
                )

            self._cleanup_orphan_metadata(finished_at)
            self._scan_processed_entities = self._scan_total_entities
            self._scan_in_progress = False
            self._rebuild_visible_buckets_from_device_states(finished_at)
            self._has_complete_snapshot = True
            self._request_storage_save()
            self._update_refresh_timer()
            if version != self._scan_version:
                return
            self._publish_snapshot(finished_at)
        except asyncio.CancelledError:
            raise
        except Exception:
            LOGGER.exception("Device Availability Monitor scan failed")
            raise
        finally:
            current_task = asyncio.current_task()
            if self._current_scan_task is current_task:
                self._current_scan_task = None
            if version == self._scan_version and self._scan_in_progress:
                self._scan_in_progress = False
                self._update_refresh_timer()

    def _update_refresh_timer(self) -> None:
        """Start or stop the periodic refresh timer based on current state."""
        should_run = (
            not self._scan_in_progress and bool(self._offline_devices or self._flapping_devices)
        )
        if should_run and self._unsub_refresh_timer is None:
            self._unsub_refresh_timer = async_track_time_interval(
                self.hass,
                self._async_handle_periodic_refresh,
                timedelta(seconds=self.config.ui_refresh_interval),
            )
            return

        if not should_run and self._unsub_refresh_timer is not None:
            self._unsub_refresh_timer()
            self._unsub_refresh_timer = None

    @callback
    def _async_handle_periodic_refresh(self, now: datetime) -> None:
        """Refresh the published snapshot while devices remain unstable."""
        self._rebuild_visible_buckets_from_device_states(now)
        self._cleanup_orphan_metadata(now)
        self._publish_snapshot(now)
        self._update_refresh_timer()

    def _cleanup_orphan_metadata(self, now: datetime) -> bool:
        """Drop recovered-device metadata for devices that no longer exist."""
        active_device_ids = set(self._device_states)
        if not active_device_ids:
            had_entries = bool(self.last_recovered_at)
            self.last_recovered_at.clear()
            if had_entries:
                self._request_storage_save()
            return had_entries

        cutoff = now - timedelta(hours=self.config.cleanup_orphan_after_hours)
        updated = {
            device_id: recovered_at
            for device_id, recovered_at in self.last_recovered_at.items()
            if device_id in active_device_ids or recovered_at >= cutoff
        }
        changed = updated != self.last_recovered_at
        if changed:
            self.last_recovered_at = updated
            self._request_storage_save()
        return changed

    def _reset_snapshot_state(self) -> None:
        """Clear the exposed snapshot buckets without touching device state."""
        self._offline_devices.clear()
        self._offline_device_index.clear()
        self._critical_devices.clear()
        self._critical_device_index.clear()
        self._degraded_devices.clear()
        self._degraded_device_index.clear()
        self._low_battery_devices.clear()
        self._low_battery_device_index.clear()
        self._flapping_devices.clear()
        self._flapping_device_index.clear()
        self._by_integration.clear()
        self._offline_warning_count = 0
        self._snapshot_dynamic["unavailable_count"] = 0
        self._snapshot_dynamic["offline_count"] = 0
        self._snapshot_dynamic["critical_count"] = 0
        self._snapshot_dynamic["warning_count"] = 0
        self._snapshot_dynamic["degraded_count"] = 0
        self._snapshot_dynamic["flapping_count"] = 0
        self._snapshot_dynamic["low_battery_count"] = 0
        self._snapshot_dynamic["offline_devices_total"] = 0
        self._snapshot_dynamic["offline_devices_truncated"] = False
        self._snapshot_dynamic["critical_devices_total"] = 0
        self._snapshot_dynamic["critical_devices_truncated"] = False
        self._snapshot_dynamic["degraded_devices_total"] = 0
        self._snapshot_dynamic["degraded_devices_truncated"] = False
        self._snapshot_dynamic["low_battery_devices_total"] = 0
        self._snapshot_dynamic["low_battery_devices_truncated"] = False
        self._snapshot_dynamic["flapping_devices_total"] = 0
        self._snapshot_dynamic["flapping_devices_truncated"] = False

    def _refresh_snapshot_totals(self) -> None:
        """Refresh the top-level counters derived from the snapshot buckets."""
        offline_total = len(self._offline_devices)
        critical_total = len(self._critical_devices)
        degraded_total = len(self._degraded_devices)
        low_battery_total = len(self._low_battery_devices)
        flapping_total = len(self._flapping_devices)

        self._snapshot_dynamic["unavailable_count"] = offline_total
        self._snapshot_dynamic["offline_count"] = offline_total
        self._snapshot_dynamic["critical_count"] = critical_total
        self._snapshot_dynamic["warning_count"] = self._offline_warning_count
        self._snapshot_dynamic["degraded_count"] = degraded_total
        self._snapshot_dynamic["flapping_count"] = flapping_total
        self._snapshot_dynamic["low_battery_count"] = low_battery_total
        self._snapshot_dynamic["offline_devices_total"] = offline_total
        self._snapshot_dynamic["offline_devices_truncated"] = (
            offline_total > MAX_EXPOSED_OFFLINE_DEVICES
        )
        self._snapshot_dynamic["critical_devices_total"] = critical_total
        self._snapshot_dynamic["critical_devices_truncated"] = (
            critical_total > MAX_EXPOSED_CRITICAL_DEVICES
        )
        self._snapshot_dynamic["degraded_devices_total"] = degraded_total
        self._snapshot_dynamic["degraded_devices_truncated"] = (
            degraded_total > MAX_EXPOSED_OFFLINE_DEVICES
        )
        self._snapshot_dynamic["low_battery_devices_total"] = low_battery_total
        self._snapshot_dynamic["low_battery_devices_truncated"] = (
            low_battery_total > MAX_EXPOSED_OFFLINE_DEVICES
        )
        self._snapshot_dynamic["flapping_devices_total"] = flapping_total
        self._snapshot_dynamic["flapping_devices_truncated"] = (
            flapping_total > MAX_EXPOSED_OFFLINE_DEVICES
        )
        self._snapshot_dynamic["scan_in_progress"] = self._scan_in_progress
        self._snapshot_dynamic["scan_processed_entities"] = self._scan_processed_entities
        self._snapshot_dynamic["scan_total_entities"] = self._scan_total_entities

    @callback
    def _publish_snapshot(self, now: datetime) -> None:
        """Publish a fresh snapshot to coordinator entities."""
        self.async_set_updated_data(self._build_snapshot(now))

    def _build_snapshot(self, now: datetime) -> dict[str, Any]:
        """Build the data snapshot exposed to sensor entities."""
        self._refresh_snapshot_totals()
        self._snapshot_dynamic["updated_at"] = dt_util.as_local(now).isoformat()
        snapshot = {**self._snapshot_static, **self._snapshot_dynamic}
        snapshot["offline_devices"] = self._offline_devices[:MAX_EXPOSED_OFFLINE_DEVICES]
        snapshot["critical_devices"] = self._critical_devices[:MAX_EXPOSED_CRITICAL_DEVICES]
        snapshot["degraded_devices"] = self._degraded_devices[:MAX_EXPOSED_OFFLINE_DEVICES]
        snapshot["low_battery_devices"] = self._low_battery_devices[:MAX_EXPOSED_OFFLINE_DEVICES]
        snapshot["flapping_devices"] = self._flapping_devices[:MAX_EXPOSED_OFFLINE_DEVICES]
        snapshot["by_integration"] = dict(self._by_integration)
        return snapshot

    @callback
    def _async_handle_entity_registry_event(self, event: Event) -> None:
        """Handle entity registry changes."""
        LOGGER.debug("Entity registry update received: %s", event.data)
        self._async_schedule_registry_rebuild()

    @callback
    def _async_handle_device_registry_event(self, event: Event) -> None:
        """Handle device registry changes."""
        LOGGER.debug("Device registry update received: %s", event.data)
        self._async_schedule_registry_rebuild()

    @callback
    def _async_schedule_registry_rebuild(self) -> None:
        """Debounce registry rebuilds."""
        if self._unsub_registry_rebuild is not None:
            self._unsub_registry_rebuild()

        self._unsub_registry_rebuild = async_call_later(
            self.hass,
            REGISTRY_REBUILD_DEBOUNCE_SECONDS,
            self._async_run_registry_rebuild,
        )

    @callback
    def _async_run_registry_rebuild(self, _now: datetime) -> None:
        """Kick off the actual registry rebuild task."""
        self._unsub_registry_rebuild = None
        self.hass.async_create_task(self._async_rebuild_indexes(preserve_existing=True))

    def _bucket_upsert(
        self,
        bucket: list[dict[str, Any]],
        index: dict[str, int],
        payload: dict[str, Any],
    ) -> None:
        """Insert or replace a payload in an O(1) bucket."""
        device_id = payload["device_id"]
        existing_index = index.get(device_id)
        if existing_index is None:
            index[device_id] = len(bucket)
            bucket.append(payload)
            return
        bucket[existing_index] = payload

    def _bucket_remove(
        self,
        bucket: list[dict[str, Any]],
        index: dict[str, int],
        device_id: str,
    ) -> dict[str, Any] | None:
        """Remove a payload from an O(1) bucket."""
        existing_index = index.pop(device_id, None)
        if existing_index is None:
            return None

        removed_payload = bucket[existing_index]
        last_payload = bucket.pop()
        if existing_index < len(bucket):
            bucket[existing_index] = last_payload
            index[last_payload["device_id"]] = existing_index
        return removed_payload

    def _increment_integration_count(self, integration: str) -> None:
        """Increment the offline by-integration count."""
        key = integration or UNKNOWN_INTEGRATION
        self._by_integration[key] = self._by_integration.get(key, 0) + 1

    def _decrement_integration_count(self, integration: str) -> None:
        """Decrement the offline by-integration count."""
        key = integration or UNKNOWN_INTEGRATION
        current = self._by_integration.get(key)
        if current is None:
            return
        if current <= 1:
            self._by_integration.pop(key, None)
            return
        self._by_integration[key] = current - 1

    def _apply_entity_current_state(
        self,
        entity_id: str,
        changed_at: datetime,
        *,
        record_flap: bool,
        state: Any | None = None,
        sync_snapshot: bool = True,
    ) -> bool:
        """Apply the current state-machine value for a tracked entity."""
        monitored_entity = self.entity_index.get(entity_id)
        monitored_battery_entity = self.battery_entity_index.get(entity_id)
        if monitored_entity is None and monitored_battery_entity is None:
            return False

        device_id = (
            monitored_entity.device_id
            if monitored_entity is not None
            else monitored_battery_entity.device_id
        )
        device_state = self._device_states.get(device_id)
        if device_state is None:
            return False

        if state is None:
            state = self.hass.states.get(entity_id)

        changed = False

        if monitored_entity is not None:
            desired_offline = is_entity_offline(
                state.state if state is not None else None,
                self.config.treat_unknown_as_offline,
            )
            offline_since = (
                self._offline_started_at_from_state(state, changed_at)
                if desired_offline
                else None
            )
            changed |= self._set_entity_offline_state(
                device_state,
                entity_id,
                desired_offline,
                changed_at,
                offline_since,
            )

        if monitored_battery_entity is not None:
            battery_percent = self._battery_percent_from_state(
                state,
                self.config.treat_battery_unavailable_unknown_as_low,
            )
            changed |= self._set_entity_battery_state(
                device_state,
                entity_id,
                battery_percent,
            )

        if changed:
            if sync_snapshot:
                self._apply_device_snapshot(
                    device_state,
                    changed_at,
                    record_flap=record_flap,
                )
            else:
                self._update_device_health(
                    device_state,
                    changed_at,
                    record_flap=record_flap,
                )
            self._request_storage_save()
        return changed

    def _set_entity_offline_state(
        self,
        device_state: DeviceState,
        entity_id: str,
        desired_offline: bool,
        changed_at: datetime,
        offline_since: datetime | None = None,
    ) -> bool:
        """Apply a tracked entity's offline status incrementally."""
        currently_offline = entity_id in device_state.offline_entities
        current_since = device_state.offline_entity_since.get(entity_id)
        changed = False

        if desired_offline:
            started_at = offline_since or changed_at
            if not currently_offline:
                device_state.offline_entities.add(entity_id)
                changed = True
            if current_since is None or started_at < current_since:
                device_state.offline_entity_since[entity_id] = started_at
                changed = True
        else:
            if not currently_offline:
                return False
            device_state.offline_entities.discard(entity_id)
            device_state.offline_entity_since.pop(entity_id, None)
            changed = True

        if changed:
            self._recalculate_offline_metadata(device_state)
        return changed

    def _set_entity_battery_state(
        self,
        device_state: DeviceState,
        entity_id: str,
        battery_percent: float | None,
    ) -> bool:
        """Apply a tracked entity's battery state incrementally."""
        current_percent = device_state.battery_entity_values.get(entity_id)
        if battery_percent is None:
            if current_percent is None:
                return False
            device_state.battery_entity_values.pop(entity_id, None)
            self._recalculate_battery_metadata(device_state)
            return True

        if current_percent is not None and current_percent == battery_percent:
            return False

        device_state.battery_entity_values[entity_id] = battery_percent
        self._recalculate_battery_metadata(device_state)
        return True

    def _recalculate_offline_metadata(self, device_state: DeviceState) -> None:
        """Recalculate offline metadata after a tracked entity set changed."""
        if not device_state.offline_entities:
            device_state.offline_since = None
            device_state.source_offline_entity_id = None
            device_state.entity_domains.clear()
            return

        relevant_entities = [
            entity_id
            for entity_id in device_state.offline_entities
            if self._is_relevant_offline_entity(entity_id)
        ]
        if not relevant_entities:
            device_state.offline_since = None
            device_state.source_offline_entity_id = None
            device_state.entity_domains.clear()
            return

        source_entity_id: str | None = None
        source_since: datetime | None = None
        for entity_id in relevant_entities:
            since = device_state.offline_entity_since.get(entity_id)
            if since is None:
                continue
            if (
                source_since is None
                or since < source_since
                or (
                    since == source_since
                    and source_entity_id is not None
                    and entity_id < source_entity_id
                )
            ):
                source_since = since
                source_entity_id = entity_id

        if source_entity_id is None or source_since is None:
            # Every current offline entity should have a start time. If one is
            # missing, keep the device-level timestamp cleared rather than
            # carrying forward a historical value from a previous outage.
            device_state.offline_since = None
            device_state.source_offline_entity_id = None
            device_state.entity_domains = {
                self.entity_index[entity_id].entity_domain
                for entity_id in device_state.offline_entities
                if entity_id in self.entity_index
            }
            return

        device_state.offline_since = source_since
        device_state.source_offline_entity_id = source_entity_id
        device_state.entity_domains = {
            self.entity_index[entity_id].entity_domain
            for entity_id in device_state.offline_entities
            if entity_id in self.entity_index
        }

    def _recalculate_battery_metadata(self, device_state: DeviceState) -> None:
        """Recalculate battery metadata after a tracked entity set changed."""
        source_entity_id: str | None = None
        source_percent: float | None = None

        for entity_id, percent in device_state.battery_entity_values.items():
            if (
                source_percent is None
                or percent < source_percent
                or (
                    percent == source_percent
                    and source_entity_id is not None
                    and entity_id < source_entity_id
                )
            ):
                source_percent = percent
                source_entity_id = entity_id

        device_state.source_battery_entity_id = source_entity_id
        device_state.battery_percent = source_percent

    def _evaluate_device(self, device_state: DeviceState) -> str:
        """Return the current health state for a device."""
        if self._is_device_offline(device_state):
            return DEVICE_STATUS_OFFLINE
        if self._is_device_degraded(device_state):
            return DEVICE_STATUS_DEGRADED
        return DEVICE_STATUS_ONLINE

    def _is_device_offline(self, device_state: DeviceState) -> bool:
        """Return whether a device should be considered offline."""
        if not device_state.offline_entities:
            return False

        strategy = self.config.offline_strategy
        if strategy == "any":
            return True

        if strategy == "core":
            return any(
                self._is_core_entity(entity_id)
                for entity_id in device_state.offline_entities
            )

        if strategy == "quorum":
            return len(device_state.offline_entities) >= len(device_state.entity_ids) / 2

        return any(
            self._is_core_entity(entity_id)
            for entity_id in device_state.offline_entities
        )

    def _is_device_degraded(self, device_state: DeviceState) -> bool:
        """Return whether a device should be considered degraded."""
        if (
            device_state.battery_percent is not None
            and device_state.battery_percent < self.config.low_battery_threshold
        ):
            return True

        if any(
            not self._is_core_entity(entity_id)
            for entity_id in device_state.offline_entities
        ):
            return True

        if device_state.flap_count >= FLAP_THRESHOLD:
            return True

        return False

    def _record_flap(self, device_state: DeviceState, now: datetime) -> None:
        """Record a flap transition for a device."""
        device_state.flap_history.append(now)
        self._trim_flap_history(device_state, now)

    def _trim_flap_history(self, device_state: DeviceState, now: datetime) -> bool:
        """Drop flap history outside the rolling window."""
        cutoff = now - timedelta(seconds=FLAP_WINDOW_SECONDS)
        changed = False
        while device_state.flap_history and device_state.flap_history[0] < cutoff:
            device_state.flap_history.popleft()
            changed = True
        device_state.flap_count = len(device_state.flap_history)
        return changed

    def _rebuild_visible_buckets_from_device_states(self, now: datetime) -> None:
        """Rebuild the exposed buckets from the canonical device state."""
        self._reset_snapshot_state()
        for device_state in self._device_states.values():
            self._apply_device_snapshot(device_state, now, record_flap=False)

    def _apply_device_snapshot(
        self,
        device_state: DeviceState,
        changed_at: datetime,
        *,
        record_flap: bool,
    ) -> None:
        """Sync a single device into the exposed snapshot buckets."""
        self._update_device_health(
            device_state,
            changed_at,
            record_flap=record_flap,
        )

        self._sync_offline_bucket(device_state, changed_at)
        self._sync_degraded_bucket(device_state, changed_at)
        self._sync_low_battery_bucket(device_state)
        self._sync_flapping_bucket(device_state, changed_at)

    def _update_device_health(
        self,
        device_state: DeviceState,
        changed_at: datetime,
        *,
        record_flap: bool,
    ) -> None:
        """Refresh canonical device health without touching exposed buckets."""
        previous_health = device_state.health_state
        current_health = self._evaluate_device(device_state)

        if record_flap and current_health != previous_health:
            self._record_flap(device_state, changed_at)
            current_health = self._evaluate_device(device_state)

        device_state.health_state = current_health
        if current_health == DEVICE_STATUS_DEGRADED:
            device_state.health_reasons = set(self._get_degraded_reasons(device_state))
        else:
            device_state.health_reasons.clear()
        if previous_health == DEVICE_STATUS_OFFLINE and current_health != DEVICE_STATUS_OFFLINE:
            self.last_recovered_at[device_state.device_id] = changed_at

    def _sync_offline_bucket(self, device_state: DeviceState, now: datetime) -> None:
        """Keep the offline snapshot bucket aligned with the device state."""
        device_id = device_state.device_id
        payload = self._serialize_offline_device(device_state, now)
        existing_index = self._offline_device_index.get(device_id)

        if payload is None:
            if existing_index is None:
                return
            existing_payload = self._offline_devices[existing_index]
            previous_integration = existing_payload.get("integration", UNKNOWN_INTEGRATION)
            previous_severity = existing_payload.get("severity")
            self._bucket_remove(self._offline_devices, self._offline_device_index, device_id)
            self._decrement_integration_count(previous_integration)
            if previous_severity == SEVERITY_WARNING:
                self._offline_warning_count -= 1
            if previous_severity == SEVERITY_CRITICAL:
                self._bucket_remove(self._critical_devices, self._critical_device_index, device_id)
            return

        if existing_index is None:
            self._bucket_upsert(self._offline_devices, self._offline_device_index, payload)
            self._increment_integration_count(payload.get("integration", UNKNOWN_INTEGRATION))
        else:
            existing_payload = self._offline_devices[existing_index]
            previous_integration = existing_payload.get("integration", UNKNOWN_INTEGRATION)
            previous_severity = existing_payload.get("severity")
            existing_payload.clear()
            existing_payload.update(payload)
            if previous_integration != payload.get("integration", UNKNOWN_INTEGRATION):
                self._decrement_integration_count(previous_integration)
                self._increment_integration_count(payload.get("integration", UNKNOWN_INTEGRATION))
            if previous_severity == SEVERITY_WARNING and payload.get("severity") != SEVERITY_WARNING:
                self._offline_warning_count -= 1
            elif previous_severity != SEVERITY_WARNING and payload.get("severity") == SEVERITY_WARNING:
                self._offline_warning_count += 1

        if payload.get("severity") == SEVERITY_CRITICAL:
            self._bucket_upsert(self._critical_devices, self._critical_device_index, payload)
        else:
            self._bucket_remove(self._critical_devices, self._critical_device_index, device_id)

    def _sync_degraded_bucket(self, device_state: DeviceState, now: datetime) -> None:
        """Keep the degraded snapshot bucket aligned with the device state."""
        device_id = device_state.device_id
        payload = self._serialize_degraded_device(device_state, now)
        existing_index = self._degraded_device_index.get(device_id)

        if payload is None:
            if existing_index is not None:
                self._bucket_remove(self._degraded_devices, self._degraded_device_index, device_id)
            return

        if existing_index is None:
            self._bucket_upsert(self._degraded_devices, self._degraded_device_index, payload)
            return

        self._degraded_devices[existing_index].clear()
        self._degraded_devices[existing_index].update(payload)

    def _sync_low_battery_bucket(self, device_state: DeviceState) -> None:
        """Keep the low battery snapshot bucket aligned with the device state."""
        device_id = device_state.device_id
        payload = self._serialize_low_battery_device(device_state)
        existing_index = self._low_battery_device_index.get(device_id)

        if payload is None:
            if existing_index is not None:
                self._bucket_remove(self._low_battery_devices, self._low_battery_device_index, device_id)
            return

        if existing_index is None:
            self._bucket_upsert(self._low_battery_devices, self._low_battery_device_index, payload)
            return

        self._low_battery_devices[existing_index].clear()
        self._low_battery_devices[existing_index].update(payload)

    def _sync_flapping_bucket(self, device_state: DeviceState, now: datetime) -> None:
        """Keep the flapping snapshot bucket aligned with the device state."""
        device_id = device_state.device_id
        if self._trim_flap_history(device_state, now):
            self._request_storage_save()
        payload = self._serialize_flapping_device(device_state)
        existing_index = self._flapping_device_index.get(device_id)

        if payload is None:
            if existing_index is not None:
                self._bucket_remove(self._flapping_devices, self._flapping_device_index, device_id)
            return

        if existing_index is None:
            self._bucket_upsert(self._flapping_devices, self._flapping_device_index, payload)
            return

        self._flapping_devices[existing_index].clear()
        self._flapping_devices[existing_index].update(payload)

    def _is_relevant_offline_entity(self, entity_id: str) -> bool:
        """Return whether an offline entity should participate in offline evaluation."""
        monitored_entity = self.entity_index.get(entity_id)
        if monitored_entity is None:
            return False
        if self.config.offline_strategy == "core":
            return monitored_entity.is_core
        return True

    def _resolve_low_battery_source_entity_id(
        self, device_state: DeviceState
    ) -> str | None:
        """Select the representative low battery entity for a device record."""
        source_entity_id: str | None = None
        source_percent: float | None = None
        for entity_id, percent in device_state.battery_entity_values.items():
            if percent >= self.config.low_battery_threshold:
                continue
            if (
                source_percent is None
                or percent < source_percent
                or (
                    percent == source_percent
                    and source_entity_id is not None
                    and entity_id < source_entity_id
                )
            ):
                source_percent = percent
                source_entity_id = entity_id
        return source_entity_id

    def _resolve_offline_source_entity_id(
        self, device_state: DeviceState
    ) -> str | None:
        """Select the representative offline entity for a device record."""
        source_entity_id: str | None = None
        source_since: datetime | None = None

        for entity_id in device_state.offline_entities:
            if not self._is_relevant_offline_entity(entity_id):
                continue
            since = device_state.offline_entity_since.get(entity_id)
            if since is None:
                continue
            if (
                source_since is None
                or since < source_since
                or (
                    since == source_since
                    and source_entity_id is not None
                    and entity_id < source_entity_id
                )
            ):
                source_since = since
                source_entity_id = entity_id

        if source_entity_id is not None:
            return source_entity_id

        if device_state.offline_entities:
            return sorted(device_state.offline_entities)[0]

        return None

    def _resolve_degraded_source_entity_id(
        self, device_state: DeviceState
    ) -> str | None:
        """Select a representative entity for a degraded device."""
        low_battery_source = self._resolve_low_battery_source_entity_id(device_state)
        if low_battery_source is not None:
            return low_battery_source

        non_core_offline = [
            entity_id
            for entity_id in device_state.offline_entities
            if not self._is_core_entity(entity_id)
        ]
        if non_core_offline:
            non_core_offline.sort(
                key=lambda entity_id: (
                    device_state.offline_entity_since.get(entity_id) is None,
                    device_state.offline_entity_since.get(entity_id) or dt_util.utcnow(),
                    entity_id,
                )
            )
            return non_core_offline[0]

        if device_state.entity_ids:
            return sorted(device_state.entity_ids)[0]

        return None

    def _get_degraded_reasons(self, device_state: DeviceState) -> list[str]:
        """Return the active degraded reasons for a device."""
        reasons: list[str] = []
        if (
            device_state.battery_percent is not None
            and device_state.battery_percent < self.config.low_battery_threshold
        ):
            reasons.append("low_battery")
        if any(
            not self._is_core_entity(entity_id)
            for entity_id in device_state.offline_entities
        ):
            reasons.append("non_core_offline")
        if device_state.flap_count >= FLAP_THRESHOLD:
            reasons.append("flap")
        return reasons

    def _is_core_entity(self, entity_id: str) -> bool:
        """Return whether an entity belongs to a core domain."""
        monitored_entity = self.entity_index.get(entity_id)
        return monitored_entity.is_core if monitored_entity is not None else False

    def _serialize_offline_device(
        self,
        device_state: DeviceState,
        now: datetime,
    ) -> dict[str, Any] | None:
        """Serialize a device into an offline payload."""
        if not self._is_device_offline(device_state):
            return None

        offline_source_entity_id = self._resolve_offline_source_entity_id(device_state)
        if offline_source_entity_id is not None:
            integration = self.entity_index.get(offline_source_entity_id, None)
            integration_name = (
                integration.integration
                if integration is not None
                else device_state.integration or UNKNOWN_INTEGRATION
            )
        else:
            integration_name = device_state.integration or UNKNOWN_INTEGRATION

        offline_since = device_state.offline_since or now
        duration = max(0, int((now - offline_since).total_seconds()))
        severity = self._severity_for_duration(duration)
        offline_entities = sorted(device_state.offline_entities)
        exposed_entities = offline_entities[:MAX_EXPOSED_OFFLINE_ENTITIES_PER_DEVICE]

        return {
            "device_id": device_state.device_id,
            "device_name": device_state.device_name,
            "integration": integration_name,
            "domains": sorted(device_state.entity_domains),
            "offline_since": dt_util.as_local(offline_since).isoformat(),
            "offline_duration": duration,
            "severity": severity,
            "health_state": DEVICE_STATUS_OFFLINE,
            "source_entity_id": offline_source_entity_id,
            "offline_entities": exposed_entities,
            "offline_entities_total": len(offline_entities),
            "offline_entities_truncated": len(offline_entities) > len(exposed_entities),
            "last_recovered_at": (
                dt_util.as_local(self.last_recovered_at[device_state.device_id]).isoformat()
                if device_state.device_id in self.last_recovered_at
                else None
            ),
        }

    def _serialize_degraded_device(
        self,
        device_state: DeviceState,
        now: datetime,
    ) -> dict[str, Any] | None:
        """Serialize a device into a degraded payload."""
        if self._evaluate_device(device_state) != DEVICE_STATUS_DEGRADED:
            return None

        reasons = self._get_degraded_reasons(device_state)
        source_entity_id = self._resolve_degraded_source_entity_id(device_state)
        if source_entity_id is not None:
            monitored_entity = self.entity_index.get(source_entity_id)
            integration_name = (
                monitored_entity.integration
                if monitored_entity is not None
                else device_state.integration or UNKNOWN_INTEGRATION
            )
        else:
            integration_name = device_state.integration or UNKNOWN_INTEGRATION

        battery_percent = device_state.battery_percent
        display_battery_percent: int | float | None
        if battery_percent is None:
            display_battery_percent = None
        elif float(battery_percent).is_integer():
            display_battery_percent = int(battery_percent)
        else:
            display_battery_percent = round(battery_percent, 2)

        non_core_offline_entities = sorted(
            entity_id
            for entity_id in device_state.offline_entities
            if not self._is_core_entity(entity_id)
        )

        return {
            "device_id": device_state.device_id,
            "device_name": device_state.device_name,
            "integration": integration_name,
            "health_state": DEVICE_STATUS_DEGRADED,
            "reasons": reasons,
            "battery_percent": display_battery_percent,
            "battery_source_entity_id": device_state.source_battery_entity_id,
            "source_entity_id": source_entity_id,
            "non_core_offline_entities": non_core_offline_entities,
            "flap_count": device_state.flap_count,
            "updated_at": dt_util.as_local(now).isoformat(),
        }

    def _serialize_low_battery_device(
        self,
        device_state: DeviceState,
    ) -> dict[str, Any] | None:
        """Serialize a device into a low battery payload."""
        low_values = {
            entity_id: percent
            for entity_id, percent in device_state.battery_entity_values.items()
            if percent < self.config.low_battery_threshold
        }
        if not low_values:
            return None

        source_entity_id: str | None = None
        source_percent: float | None = None
        for entity_id, percent in low_values.items():
            if (
                source_percent is None
                or percent < source_percent
                or (
                    percent == source_percent
                    and source_entity_id is not None
                    and entity_id < source_entity_id
                )
            ):
                source_percent = percent
                source_entity_id = entity_id

        if source_entity_id is not None:
            monitored_entity = self.battery_entity_index.get(source_entity_id)
            integration_name = (
                monitored_entity.integration
                if monitored_entity is not None
                else device_state.integration or UNKNOWN_INTEGRATION
            )
        else:
            integration_name = device_state.integration or UNKNOWN_INTEGRATION

        display_battery_percent: int | float
        assert source_percent is not None
        display_battery_percent = (
            int(source_percent)
            if float(source_percent).is_integer()
            else round(source_percent, 2)
        )
        battery_entities = sorted(low_values)
        exposed_entities = battery_entities[:MAX_EXPOSED_OFFLINE_ENTITIES_PER_DEVICE]

        return {
            "device_id": device_state.device_id,
            "device_name": device_state.device_name,
            "integration": integration_name,
            "battery_percent": display_battery_percent,
            "battery_source_entity_id": source_entity_id,
            "battery_entities": exposed_entities,
            "battery_entities_total": len(battery_entities),
            "battery_entities_truncated": len(battery_entities) > len(exposed_entities),
        }

    def _serialize_flapping_device(
        self,
        device_state: DeviceState,
    ) -> dict[str, Any] | None:
        """Serialize a device into a flapping payload."""
        if device_state.flap_count <= 0:
            return None

        return {
            "device_id": device_state.device_id,
            "device_name": device_state.device_name,
            "integration": device_state.integration or UNKNOWN_INTEGRATION,
            "health_state": device_state.health_state,
            "flap_count": device_state.flap_count,
        }

    def _severity_for_duration(self, duration_seconds: int) -> str | None:
        """Return the severity for an offline duration."""
        if duration_seconds >= self.config.critical_threshold:
            return SEVERITY_CRITICAL
        if duration_seconds >= self.config.warning_threshold:
            return SEVERITY_WARNING
        return None

    def _is_battery_entity(self, entity_entry: er.RegistryEntry) -> bool:
        """Return whether an entity registry entry should be tracked as a battery sensor."""
        return (
            getattr(entity_entry, "original_device_class", None) == "battery"
            or getattr(entity_entry, "device_class", None) == "battery"
        )

    def _is_battery_low(self, battery_percent: float) -> bool:
        """Return whether a battery percentage should be considered low."""
        return battery_percent < self.config.low_battery_threshold

    def _battery_percent_from_state(
        self,
        state,
        treat_unavailable_unknown_as_low: bool,
    ) -> float | None:
        """Return a normalized battery percentage for the current entity state."""
        if state is None:
            return None

        raw_state = getattr(state, "state", None)
        if raw_state in {"unavailable", "unknown"}:
            return 0.0 if treat_unavailable_unknown_as_low else None

        if raw_state is None:
            return None

        raw_text = str(raw_state).strip()
        if raw_text.endswith("%"):
            raw_text = raw_text[:-1].strip()

        try:
            battery_percent = float(raw_text)
        except (TypeError, ValueError):
            return None

        if math.isnan(battery_percent) or math.isinf(battery_percent):
            return None
        if battery_percent < 0 or battery_percent > 100:
            return None

        return battery_percent

    def _offline_started_at_from_state(
        self,
        state,
        fallback: datetime,
    ) -> datetime:
        """Return the best-known time when the current offline state began."""
        if state is None:
            return fallback

        last_changed = getattr(state, "last_changed", None)
        if isinstance(last_changed, datetime):
            return last_changed

        return fallback

    @staticmethod
    def _resolve_device_name(
        device_entry: dr.DeviceEntry | None,
        entity_entry: er.RegistryEntry,
    ) -> str:
        """Resolve the best display name for a device."""
        if device_entry is not None:
            if device_entry.name_by_user:
                return device_entry.name_by_user
            if device_entry.name:
                return device_entry.name
        if entity_entry.original_name:
            return entity_entry.original_name
        return entity_entry.entity_id
