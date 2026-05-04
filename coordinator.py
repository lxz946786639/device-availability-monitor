"""Coordinator for Device Availability Monitor."""

from __future__ import annotations

import asyncio
import math
from collections import Counter
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
from homeassistant.helpers.event import (
    async_call_later,
    async_track_time_interval,
)
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
    CONF_TRACKED_DOMAINS,
    CONF_TREAT_BATTERY_UNAVAILABLE_UNKNOWN_AS_LOW,
    CONF_TREAT_UNKNOWN_AS_OFFLINE,
    CONF_UI_REFRESH_INTERVAL,
    CONF_WARNING_THRESHOLD,
    DEFAULT_CLEANUP_ORPHAN_AFTER_HOURS,
    DEFAULT_CRITICAL_THRESHOLD,
    DEFAULT_LOW_BATTERY_THRESHOLD,
    DEFAULT_TRACKED_DOMAINS,
    DEFAULT_TREAT_BATTERY_UNAVAILABLE_UNKNOWN_AS_LOW,
    DEFAULT_TREAT_UNKNOWN_AS_OFFLINE,
    DEFAULT_UI_REFRESH_INTERVAL,
    DEFAULT_WARNING_THRESHOLD,
    DOMAIN,
    EVENT_STATE_CHANGED,
    MAX_EXPOSED_CRITICAL_DEVICES,
    MAX_EXPOSED_OFFLINE_DEVICES,
    MAX_EXPOSED_OFFLINE_ENTITIES_PER_DEVICE,
    NAME,
    REGISTRY_REBUILD_DEBOUNCE_SECONDS,
    SEVERITY_CRITICAL,
    SEVERITY_WARNING,
    UNKNOWN_INTEGRATION,
)

LOGGER = logging.getLogger(__name__)
SCAN_BATCH_SIZE = 500


@dataclass(slots=True)
class MonitorConfig:
    """Normalized runtime configuration."""

    warning_threshold: int = DEFAULT_WARNING_THRESHOLD
    critical_threshold: int = DEFAULT_CRITICAL_THRESHOLD
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


@dataclass(slots=True)
class MonitoredDevice:
    """Aggregated metadata for a monitored device."""

    device_id: str
    device_name: str


@dataclass(slots=True)
class OfflineRecord:
    """Current offline state for a device."""

    device_id: str
    device_name: str
    integration: str
    offline_since: datetime
    offline_entities: set[str] = field(default_factory=set)
    offline_entity_since: dict[str, datetime] = field(default_factory=dict)
    entity_domains: set[str] = field(default_factory=set)
    source_entity_id: str | None = None
    last_recovered_at: datetime | None = None


@dataclass(slots=True)
class LowBatteryRecord:
    """Current low battery state for a device."""

    device_id: str
    device_name: str
    integration: str
    battery_percent: float
    battery_entities: set[str] = field(default_factory=set)
    battery_entity_values: dict[str, float] = field(default_factory=dict)
    source_entity_id: str | None = None


def config_from_entry(entry: ConfigEntry) -> MonitorConfig:
    """Build runtime config from the config entry."""
    merged: dict[str, Any] = {
        CONF_WARNING_THRESHOLD: DEFAULT_WARNING_THRESHOLD,
        CONF_CRITICAL_THRESHOLD: DEFAULT_CRITICAL_THRESHOLD,
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


class DeviceAvailabilityMonitorCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Track unavailable devices and publish snapshot data."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        """Initialize the coordinator."""
        super().__init__(hass, LOGGER, name=NAME)
        self.entry = entry
        self.config = config_from_entry(entry)
        self.entity_index: dict[str, MonitoredEntity] = {}
        self.battery_entity_index: dict[str, MonitoredEntity] = {}
        self.device_index: dict[str, MonitoredDevice] = {}
        self.offline_records: dict[str, OfflineRecord] = {}
        self.low_battery_records: dict[str, LowBatteryRecord] = {}
        self.last_recovered_at: dict[str, datetime] = {}
        self._unsub_state_listener: CALLBACK_TYPE | None = None
        self._unsub_entity_registry: CALLBACK_TYPE | None = None
        self._unsub_device_registry: CALLBACK_TYPE | None = None
        self._unsub_registry_rebuild: CALLBACK_TYPE | None = None
        self._unsub_refresh_timer: CALLBACK_TYPE | None = None
        self._scan_task: asyncio.Task[None] | None = None
        self._scan_generation = 0
        self._scan_in_progress = False
        self._scan_processed_entities = 0
        self._scan_total_entities = 0
        self._pending_entity_refreshes: set[str] = set()

    async def async_initialize(self) -> None:
        """Initialize indexes, snapshot data, and listeners."""
        await self._async_rebuild_indexes(preserve_existing=False)

        self._unsub_entity_registry = self.hass.bus.async_listen(
            er.EVENT_ENTITY_REGISTRY_UPDATED,
            self._async_handle_entity_registry_event,
        )
        self._unsub_device_registry = self.hass.bus.async_listen(
            dr.EVENT_DEVICE_REGISTRY_UPDATED,
            self._async_handle_device_registry_event,
        )

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
        if self._scan_task is not None:
            self._scan_task.cancel()
            with suppress(asyncio.CancelledError):
                await self._scan_task
            self._scan_task = None

    async def async_reset_stats(self) -> None:
        """Reset runtime state and rebuild the snapshot."""
        LOGGER.info("Resetting Device Availability Monitor statistics")
        self.offline_records.clear()
        self.low_battery_records.clear()
        self.last_recovered_at.clear()
        self._pending_entity_refreshes.clear()
        await self._async_rebuild_indexes(preserve_existing=False)

    async def _async_rebuild_indexes(self, preserve_existing: bool) -> None:
        """Rebuild entity and device indexes, then schedule a background state scan."""
        self.entity_index, self.battery_entity_index, self.device_index = self._build_indexes()
        self._scan_total_entities = len(set(self.entity_index) | set(self.battery_entity_index))
        self._scan_processed_entities = 0
        LOGGER.debug(
            "Rebuilt monitor indexes with %s offline entities, %s battery entities and %s devices",
            len(self.entity_index),
            len(self.battery_entity_index),
            len(self.device_index),
        )

        self._async_resubscribe_state_listener()
        await self._async_start_state_scan(preserve_existing)

    async def _async_start_state_scan(self, preserve_existing: bool) -> None:
        """Cancel any in-flight scan and start a new batched state scan."""
        self._scan_generation += 1
        generation = self._scan_generation

        if self._scan_task is not None:
            self._scan_task.cancel()
            with suppress(asyncio.CancelledError):
                await self._scan_task
            self._scan_task = None

        self._scan_in_progress = True
        self._scan_processed_entities = 0
        self._pending_entity_refreshes.clear()
        if not preserve_existing:
            self.offline_records = {}
            self.low_battery_records = {}
            self._update_refresh_timer()
        self._publish_snapshot(dt_util.utcnow())
        self._scan_task = self.hass.async_create_task(
            self._async_scan_states(generation, preserve_existing)
        )

    def _build_indexes(
        self,
    ) -> tuple[dict[str, MonitoredEntity], dict[str, MonitoredEntity], dict[str, MonitoredDevice]]:
        """Build fresh registry-backed indexes."""
        entity_registry = er.async_get(self.hass)
        device_registry = dr.async_get(self.hass)

        entity_index: dict[str, MonitoredEntity] = {}
        battery_entity_index: dict[str, MonitoredEntity] = {}
        device_index: dict[str, MonitoredDevice] = {}
        device_name_cache: dict[str, str] = {}

        for entry in entity_registry.entities.values():
            entity_id = entry.entity_id
            device_id = entry.device_id
            if device_id is None:
                continue
            if entry.disabled_by is not None:
                continue

            domain = split_entity_id(entity_id)[0]
            integration = entry.platform or UNKNOWN_INTEGRATION
            is_offline_entity = domain in self.config.tracked_domains
            is_battery_entity = self._is_battery_entity(entry)
            tracks_offline = is_offline_entity and domain not in self.config.exclude_domains
            tracks_battery = is_battery_entity

            if not tracks_offline and not tracks_battery:
                continue
            if entity_id in self.config.exclude_entities:
                continue
            if device_id in self.config.exclude_devices:
                continue
            if integration in self.config.exclude_integrations:
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
            )
            if tracks_offline:
                entity_index[entity_id] = monitored_entity
            if tracks_battery:
                battery_entity_index[entity_id] = monitored_entity

            monitored_device = device_index.setdefault(
                device_id,
                MonitoredDevice(device_id=device_id, device_name=device_name),
            )
            monitored_device.device_name = device_name

        return entity_index, battery_entity_index, device_index

    async def _async_scan_states(
        self,
        generation: int,
        preserve_existing: bool,
    ) -> None:
        """Scan current entity states in batches to avoid large startup spikes."""
        scan_started_at = dt_util.utcnow()
        previous_records = self.offline_records.copy() if preserve_existing else {}
        treat_unknown_as_offline = self.config.treat_unknown_as_offline
        battery_treat_unknown_as_low = (
            self.config.treat_battery_unavailable_unknown_as_low
        )
        offline_builders: dict[str, OfflineRecord] = {}
        low_battery_builders: dict[str, LowBatteryRecord] = {}

        processed = 0
        entity_ids = iter(set(self.entity_index) | set(self.battery_entity_index))
        while True:
            batch = list(islice(entity_ids, SCAN_BATCH_SIZE))
            if not batch:
                break

            for entity_id in batch:
                if generation != self._scan_generation:
                    return

                tracked_offline_entity = self.entity_index.get(entity_id)
                tracked_battery_entity = self.battery_entity_index.get(entity_id)
                if tracked_offline_entity is None and tracked_battery_entity is None:
                    continue

                state = self.hass.states.get(entity_id)
                if state is None:
                    processed += 1
                    continue

                if tracked_offline_entity is not None and is_entity_offline(
                    state.state, treat_unknown_as_offline
                ):
                    offline_since = self._offline_started_at_from_state(
                        state,
                        scan_started_at,
                    )
                    self._add_builder_offline_entity(
                        offline_builders,
                        entity_id,
                        tracked_offline_entity,
                        offline_since,
                    )

                if tracked_battery_entity is not None:
                    battery_percent = self._battery_percent_from_state(
                        state,
                        battery_treat_unknown_as_low,
                    )
                    if battery_percent is not None and self._is_battery_low(
                        battery_percent
                    ):
                        self._add_builder_low_battery_entity(
                            low_battery_builders,
                            entity_id,
                            tracked_battery_entity,
                            battery_percent,
                        )

                processed += 1

            self._scan_processed_entities = processed
            self._publish_snapshot(dt_util.utcnow())
            await asyncio.sleep(0)

        if generation != self._scan_generation:
            return

        finished_at = dt_util.utcnow()
        rebuilt_records: dict[str, OfflineRecord] = {}
        for device_id, record in offline_builders.items():
            self._recalculate_record_metadata(record)
            previous = previous_records.get(device_id)
            if previous is not None and preserve_existing:
                record.offline_since = previous.offline_since
                record.last_recovered_at = previous.last_recovered_at
            else:
                record.last_recovered_at = self.last_recovered_at.get(device_id)
            rebuilt_records[device_id] = record

        for device_id in previous_records:
            if device_id not in rebuilt_records:
                self.last_recovered_at[device_id] = finished_at

        self.offline_records = rebuilt_records
        rebuilt_low_battery_records: dict[str, LowBatteryRecord] = {}
        for device_id, record in low_battery_builders.items():
            self._recalculate_low_battery_record_metadata(record)
            rebuilt_low_battery_records[device_id] = record
        self.low_battery_records = rebuilt_low_battery_records
        self._scan_processed_entities = self._scan_total_entities
        self._scan_in_progress = False
        pending_entities = tuple(self._pending_entity_refreshes)
        self._pending_entity_refreshes.clear()
        for entity_id in pending_entities:
            self._apply_entity_current_state(entity_id, finished_at)
        self._cleanup_orphan_metadata(finished_at)
        self._update_refresh_timer()
        self._publish_snapshot(finished_at)

    def _add_builder_offline_entity(
        self,
        builders: dict[str, OfflineRecord],
        entity_id: str,
        monitored_entity: MonitoredEntity,
        offline_since: datetime,
    ) -> None:
        """Add an offline entity to a bootstrap builder record."""
        device_id = monitored_entity.device_id
        monitored_device = self.device_index[device_id]
        record = builders.get(device_id)
        if record is None:
            record = OfflineRecord(
                device_id=device_id,
                device_name=monitored_device.device_name,
                integration=UNKNOWN_INTEGRATION,
                offline_since=offline_since,
                source_entity_id=entity_id,
            )
            builders[device_id] = record
        elif offline_since < record.offline_since:
            record.offline_since = offline_since
            record.source_entity_id = entity_id
        record.offline_entities.add(entity_id)
        record.offline_entity_since[entity_id] = offline_since
        record.entity_domains.add(monitored_entity.entity_domain)

    def _add_builder_low_battery_entity(
        self,
        builders: dict[str, LowBatteryRecord],
        entity_id: str,
        monitored_entity: MonitoredEntity,
        battery_percent: float,
    ) -> None:
        """Add a low battery entity to a bootstrap builder record."""
        device_id = monitored_entity.device_id
        monitored_device = self.device_index[device_id]
        record = builders.get(device_id)
        if record is None:
            record = LowBatteryRecord(
                device_id=device_id,
                device_name=monitored_device.device_name,
                integration=monitored_entity.integration or UNKNOWN_INTEGRATION,
                battery_percent=battery_percent,
                source_entity_id=entity_id,
            )
            builders[device_id] = record
        elif battery_percent < record.battery_percent:
            record.battery_percent = battery_percent
            record.source_entity_id = entity_id
        record.battery_entities.add(entity_id)
        record.battery_entity_values[entity_id] = battery_percent

    @callback
    def _async_resubscribe_state_listener(self) -> None:
        """Track all state changes and filter locally to reduce startup memory."""
        if self._unsub_state_listener is not None:
            self._unsub_state_listener()
            self._unsub_state_listener = None

        if not self.entity_index and not self.battery_entity_index:
            return

        self._unsub_state_listener = self.hass.bus.async_listen(
            EVENT_STATE_CHANGED,
            self._async_handle_state_changed,
        )

    @callback
    def _async_handle_state_changed(self, event: Event) -> None:
        """Handle a monitored entity changing state."""
        entity_id = event.data["entity_id"]
        if entity_id not in self.entity_index and entity_id not in self.battery_entity_index:
            return

        if self._scan_in_progress:
            self._pending_entity_refreshes.add(entity_id)
            return

        new_state = event.data.get("new_state")
        changed = False
        if entity_id in self.entity_index:
            desired_offline = is_entity_offline(
                new_state.state if new_state is not None else None,
                self.config.treat_unknown_as_offline,
            )
            changed |= self._set_entity_offline_state(
                entity_id,
                desired_offline,
                event.time_fired,
                self._offline_started_at_from_state(new_state, event.time_fired)
                if desired_offline
                else None,
            )
        if entity_id in self.battery_entity_index:
            changed |= self._set_entity_low_battery_state(
                entity_id,
                new_state,
                event.time_fired,
            )
        if not changed:
            return

        if entity_id in self.entity_index:
            self._cleanup_orphan_metadata(event.time_fired)
            self._update_refresh_timer()
        self._publish_snapshot(event.time_fired)

    def _apply_entity_current_state(self, entity_id: str, changed_at: datetime) -> bool:
        """Apply the current state-machine value for a tracked entity."""
        if entity_id not in self.entity_index and entity_id not in self.battery_entity_index:
            return False

        changed = False
        state = self.hass.states.get(entity_id)
        if entity_id in self.entity_index:
            desired_offline = is_entity_offline(
                state.state if state is not None else None,
                self.config.treat_unknown_as_offline,
            )
            changed |= self._set_entity_offline_state(
                entity_id,
                desired_offline,
                changed_at,
                self._offline_started_at_from_state(state, changed_at)
                if desired_offline
                else None,
            )
        if entity_id in self.battery_entity_index:
            changed |= self._set_entity_low_battery_state(
                entity_id,
                state,
                changed_at,
            )
        return changed

    def _set_entity_offline_state(
        self,
        entity_id: str,
        desired_offline: bool,
        changed_at: datetime,
        offline_since: datetime | None = None,
    ) -> bool:
        """Apply a tracked entity's offline status incrementally."""
        monitored_entity = self.entity_index.get(entity_id)
        if monitored_entity is None:
            return False

        device_id = monitored_entity.device_id
        record = self.offline_records.get(device_id)
        currently_offline = record is not None and entity_id in record.offline_entities

        if currently_offline == desired_offline:
            return False

        if desired_offline:
            offline_started_at = offline_since or changed_at
            if record is None:
                monitored_device = self.device_index[device_id]
                record = OfflineRecord(
                    device_id=device_id,
                    device_name=monitored_device.device_name,
                    integration=monitored_entity.integration or UNKNOWN_INTEGRATION,
                    offline_since=offline_started_at,
                    last_recovered_at=self.last_recovered_at.get(device_id),
                    source_entity_id=entity_id,
                )
                self.offline_records[device_id] = record
                LOGGER.info("Device went offline: %s", record.device_name)
            elif offline_started_at < record.offline_since:
                record.offline_since = offline_started_at

            record.offline_entities.add(entity_id)
            record.offline_entity_since[entity_id] = offline_started_at
            record.entity_domains.add(monitored_entity.entity_domain)
            self._recalculate_record_metadata(record)
            return True

        if record is None:
            return False

        record.offline_entities.discard(entity_id)
        record.offline_entity_since.pop(entity_id, None)
        if not record.offline_entities:
            self.last_recovered_at[device_id] = changed_at
            LOGGER.info("Device recovered: %s", record.device_name)
            self.offline_records.pop(device_id, None)
            return True

        self._recalculate_record_metadata(record)
        return True

    def _set_entity_low_battery_state(
        self,
        entity_id: str,
        state,
        changed_at: datetime,
    ) -> bool:
        """Apply a tracked entity's low battery status incrementally."""
        monitored_entity = self.battery_entity_index.get(entity_id)
        if monitored_entity is None:
            return False

        battery_percent = self._battery_percent_from_state(
            state,
            self.config.treat_battery_unavailable_unknown_as_low,
        )
        desired_low = (
            battery_percent is not None and self._is_battery_low(battery_percent)
        )

        device_id = monitored_entity.device_id
        record = self.low_battery_records.get(device_id)
        currently_low = record is not None and entity_id in record.battery_entities

        if currently_low == desired_low:
            if currently_low and record is not None and battery_percent is not None:
                previous_percent = record.battery_entity_values.get(entity_id)
                if previous_percent != battery_percent:
                    record.battery_entity_values[entity_id] = battery_percent
                    self._recalculate_low_battery_record_metadata(record)
                    return True
            return False

        if desired_low:
            battery_started_at = battery_percent if battery_percent is not None else 0.0
            if record is None:
                monitored_device = self.device_index[device_id]
                record = LowBatteryRecord(
                    device_id=device_id,
                    device_name=monitored_device.device_name,
                    integration=monitored_entity.integration or UNKNOWN_INTEGRATION,
                    battery_percent=battery_started_at,
                    source_entity_id=entity_id,
                )
                self.low_battery_records[device_id] = record
                LOGGER.info("Device low battery: %s", record.device_name)
            record.battery_entities.add(entity_id)
            record.battery_entity_values[entity_id] = battery_started_at
            self._recalculate_low_battery_record_metadata(record)
            return True

        if record is None:
            return False

        record.battery_entities.discard(entity_id)
        record.battery_entity_values.pop(entity_id, None)
        if not record.battery_entities:
            LOGGER.info("Device battery recovered: %s", record.device_name)
            self.low_battery_records.pop(device_id, None)
            return True

        self._recalculate_low_battery_record_metadata(record)
        return True

    def _recalculate_record_metadata(self, record: OfflineRecord) -> None:
        """Recalculate record metadata after its offline entity set changed."""
        record.entity_domains = {
            self.entity_index[entity_id].entity_domain
            for entity_id in record.offline_entities
            if entity_id in self.entity_index
        }
        source_entity_id = self._resolve_source_entity_id(record)
        record.source_entity_id = source_entity_id
        if source_entity_id is None:
            record.integration = UNKNOWN_INTEGRATION
            return

        source_entity = self.entity_index.get(source_entity_id)
        record.integration = (
            source_entity.integration if source_entity is not None else UNKNOWN_INTEGRATION
        )

    def _recalculate_low_battery_record_metadata(self, record: LowBatteryRecord) -> None:
        """Recalculate low battery metadata after its battery entity set changed."""
        source_entity_id = self._resolve_low_battery_source_entity_id(record)
        record.source_entity_id = source_entity_id
        if source_entity_id is None:
            record.integration = UNKNOWN_INTEGRATION
            record.battery_percent = 0.0
            return

        source_percent = record.battery_entity_values.get(source_entity_id)
        if source_percent is None:
            record.integration = UNKNOWN_INTEGRATION
            record.battery_percent = 0.0
            return

        source_entity = self.battery_entity_index.get(source_entity_id)
        record.integration = (
            source_entity.integration if source_entity is not None else UNKNOWN_INTEGRATION
        )
        record.battery_percent = source_percent

    @staticmethod
    def _resolve_low_battery_source_entity_id(
        record: LowBatteryRecord,
    ) -> str | None:
        """Select the representative low battery entity for a device record."""
        source_entity_id: str | None = None
        source_percent: float | None = None

        for entity_id, percent in record.battery_entity_values.items():
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
            return source_entity_id

        if record.battery_entities:
            return sorted(record.battery_entities)[0]

        return None

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

    @callback
    def _update_refresh_timer(self) -> None:
        """Start or stop the periodic refresh timer based on current state."""
        if self.offline_records and self._unsub_refresh_timer is None:
            self._unsub_refresh_timer = async_track_time_interval(
                self.hass,
                self._async_handle_periodic_refresh,
                timedelta(seconds=self.config.ui_refresh_interval),
            )
            return

        if not self.offline_records and self._unsub_refresh_timer is not None:
            self._unsub_refresh_timer()
            self._unsub_refresh_timer = None

    @callback
    def _async_handle_periodic_refresh(self, now: datetime) -> None:
        """Refresh the published snapshot while devices remain offline."""
        self._cleanup_orphan_metadata(now)
        self._publish_snapshot(now)

    def _cleanup_orphan_metadata(self, now: datetime) -> None:
        """Drop recovered-device metadata for devices that no longer exist."""
        active_device_ids = set(self.device_index)
        if not active_device_ids:
            self.last_recovered_at.clear()
            return

        cutoff = now - timedelta(hours=self.config.cleanup_orphan_after_hours)
        self.last_recovered_at = {
            device_id: recovered_at
            for device_id, recovered_at in self.last_recovered_at.items()
            if device_id in active_device_ids or recovered_at >= cutoff
        }

    @callback
    def _publish_snapshot(self, now: datetime) -> None:
        """Publish a fresh snapshot to coordinator entities."""
        self.async_set_updated_data(self._build_snapshot(now))

    def _build_snapshot(self, now: datetime) -> dict[str, Any]:
        """Build the data snapshot exposed to sensor entities."""
        ranked_records: list[tuple[OfflineRecord, int, str | None]] = []
        ranked_low_battery_records: list[tuple[LowBatteryRecord, float]] = []
        by_integration: Counter[str] = Counter()
        critical_count = 0
        warning_count = 0

        for record in self.offline_records.values():
            duration = max(0, int((now - record.offline_since).total_seconds()))
            severity = self._severity_for_duration(duration)

            if severity == SEVERITY_CRITICAL:
                critical_count += 1
            elif severity == SEVERITY_WARNING:
                warning_count += 1

            by_integration[record.integration] += 1
            ranked_records.append((record, duration, severity))

        for record in self.low_battery_records.values():
            ranked_low_battery_records.append((record, record.battery_percent))

        ranked_records.sort(
            key=lambda item: (
                0 if item[2] == SEVERITY_CRITICAL else 1,
                -item[1],
                item[0].device_name,
            )
        )
        ranked_low_battery_records.sort(
            key=lambda item: (
                item[1],
                item[0].device_name,
                item[0].device_id,
            )
        )

        exposed_offline_devices = [
            self._serialize_record(record, duration, severity)
            for record, duration, severity in ranked_records[:MAX_EXPOSED_OFFLINE_DEVICES]
        ]
        exposed_critical_devices: list[dict[str, Any]] = []
        for record, duration, severity in ranked_records:
            if severity != SEVERITY_CRITICAL:
                continue
            exposed_critical_devices.append(
                self._serialize_record(record, duration, severity)
            )
            if len(exposed_critical_devices) >= MAX_EXPOSED_CRITICAL_DEVICES:
                break

        exposed_low_battery_devices = [
            self._serialize_low_battery_record(record, battery_percent)
            for record, battery_percent in ranked_low_battery_records[:MAX_EXPOSED_OFFLINE_DEVICES]
        ]

        return {
            "unavailable_count": len(ranked_records),
            "critical_count": critical_count,
            "warning_count": warning_count,
            "offline_devices": exposed_offline_devices,
            "offline_devices_total": len(ranked_records),
            "offline_devices_truncated": len(ranked_records) > len(exposed_offline_devices),
            "critical_devices": exposed_critical_devices,
            "critical_devices_total": critical_count,
            "critical_devices_truncated": critical_count > len(exposed_critical_devices),
            "by_integration": dict(sorted(by_integration.items())),
            "low_battery_count": len(ranked_low_battery_records),
            "low_battery_devices": exposed_low_battery_devices,
            "low_battery_devices_total": len(ranked_low_battery_records),
            "low_battery_devices_truncated": len(ranked_low_battery_records)
            > len(exposed_low_battery_devices),
            "low_battery_threshold": self.config.low_battery_threshold,
            "treat_battery_unavailable_unknown_as_low": (
                self.config.treat_battery_unavailable_unknown_as_low
            ),
            "scan_in_progress": self._scan_in_progress,
            "scan_processed_entities": self._scan_processed_entities,
            "scan_total_entities": self._scan_total_entities,
            "updated_at": dt_util.as_local(now).isoformat(),
        }

    def _serialize_record(
        self,
        record: OfflineRecord,
        duration: int,
        severity: str | None,
    ) -> dict[str, Any]:
        """Serialize a record into a compact payload safe for state attributes."""
        offline_entities = sorted(record.offline_entities)
        exposed_entities = offline_entities[:MAX_EXPOSED_OFFLINE_ENTITIES_PER_DEVICE]

        return {
            "device_id": record.device_id,
            "device_name": record.device_name,
            "integration": record.integration,
            "domains": sorted(record.entity_domains),
            "offline_since": dt_util.as_local(record.offline_since).isoformat(),
            "offline_duration": duration,
            "severity": severity,
            "offline_entities": exposed_entities,
            "offline_entities_total": len(offline_entities),
            "offline_entities_truncated": len(offline_entities) > len(exposed_entities),
            "last_recovered_at": (
                dt_util.as_local(record.last_recovered_at).isoformat()
                if record.last_recovered_at is not None
                else None
            ),
        }

    def _serialize_low_battery_record(
        self,
        record: LowBatteryRecord,
        battery_percent: float,
    ) -> dict[str, Any]:
        """Serialize a low battery record into a compact payload safe for state attributes."""
        battery_entities = sorted(record.battery_entities)
        exposed_entities = battery_entities[:MAX_EXPOSED_OFFLINE_ENTITIES_PER_DEVICE]
        display_battery_percent: int | float
        display_battery_percent = (
            int(battery_percent)
            if float(battery_percent).is_integer()
            else round(battery_percent, 2)
        )

        return {
            "device_id": record.device_id,
            "device_name": record.device_name,
            "integration": record.integration,
            "battery_percent": display_battery_percent,
            "battery_source_entity_id": record.source_entity_id,
            "battery_entities": exposed_entities,
            "battery_entities_total": len(battery_entities),
            "battery_entities_truncated": len(battery_entities) > len(exposed_entities),
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

    @staticmethod
    def _battery_percent_from_state(
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

    def _resolve_source_entity_id(self, record: OfflineRecord) -> str | None:
        """Select the representative offline entity for a device record."""
        source_entity_id: str | None = None
        source_since: datetime | None = None

        for entity_id in record.offline_entities:
            since = record.offline_entity_since.get(entity_id)
            if since is None:
                continue

            if (
                source_since is None
                or since < source_since
                or (since == source_since and source_entity_id is not None and entity_id < source_entity_id)
            ):
                source_since = since
                source_entity_id = entity_id

        if source_entity_id is not None:
            return source_entity_id

        if record.offline_entities:
            return sorted(record.offline_entities)[0]

        return None

    @staticmethod
    def _offline_started_at_from_state(
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
