"""Constants for the Device Availability Monitor integration."""

from __future__ import annotations

from homeassistant.const import EVENT_STATE_CHANGED, Platform

DOMAIN = "device_availability_monitor"
NAME = "Device Availability Monitor"
MANUFACTURER = "noau"

DISPLAY_NAME_ZH_HANS = "设备可用性监控"


def get_display_name(language: str | None) -> str:
    """Return the localized integration display name."""
    if language and language.lower().startswith("zh"):
        return DISPLAY_NAME_ZH_HANS
    return NAME

PLATFORMS: tuple[Platform, ...] = (Platform.SENSOR,)

CONF_WARNING_THRESHOLD = "warning_threshold"
CONF_CRITICAL_THRESHOLD = "critical_threshold"
CONF_TREAT_UNKNOWN_AS_OFFLINE = "treat_unknown_as_offline"
CONF_TRACKED_DOMAINS = "tracked_domains"
CONF_EXCLUDE_DEVICES = "exclude_devices"
CONF_EXCLUDE_ENTITIES = "exclude_entities"
CONF_EXCLUDE_INTEGRATIONS = "exclude_integrations"
CONF_EXCLUDE_DOMAINS = "exclude_domains"
CONF_UI_REFRESH_INTERVAL = "ui_refresh_interval"
CONF_CLEANUP_ORPHAN_AFTER_HOURS = "cleanup_orphan_after_hours"
CONF_LOW_BATTERY_THRESHOLD = "low_battery_threshold"
CONF_TREAT_BATTERY_UNAVAILABLE_UNKNOWN_AS_LOW = (
    "treat_battery_unavailable_unknown_as_low"
)

DEFAULT_WARNING_THRESHOLD = 60
DEFAULT_CRITICAL_THRESHOLD = 600
DEFAULT_TREAT_UNKNOWN_AS_OFFLINE = False
DEFAULT_UI_REFRESH_INTERVAL = 60
DEFAULT_CLEANUP_ORPHAN_AFTER_HOURS = 24
DEFAULT_LOW_BATTERY_THRESHOLD = 20
DEFAULT_TREAT_BATTERY_UNAVAILABLE_UNKNOWN_AS_LOW = True

DEFAULT_TRACKED_DOMAINS: tuple[str, ...] = (
    "light",
    "switch",
    "cover",
    "fan",
    "climate",
    "lock",
    "media_player",
    "humidifier",
    "water_heater",
    "vacuum",
)

SUPPORTED_TRACKED_DOMAINS: tuple[str, ...] = (
    "light",
    "switch",
    "cover",
    "fan",
    "climate",
    "lock",
    "sensor",
    "binary_sensor",
    "select",
    "number",
    "media_player",
    "humidifier",
    "water_heater",
    "vacuum",
)

SERVICE_RESET_STATS = "reset_stats"

REGISTRY_REBUILD_DEBOUNCE_SECONDS = 2
MINIMUM_HOME_ASSISTANT_VERSION = "2026.4.0"
UNKNOWN_INTEGRATION = "unknown"
MAX_EXPOSED_OFFLINE_DEVICES = 200
MAX_EXPOSED_CRITICAL_DEVICES = 100
MAX_EXPOSED_OFFLINE_ENTITIES_PER_DEVICE = 10

SEVERITY_WARNING = "warning"
SEVERITY_CRITICAL = "critical"

SENSOR_UNAVAILABLE_DEVICES_LIST = "unavailable_devices_list"
SENSOR_UNAVAILABLE_BY_INTEGRATION = "unavailable_by_integration"
SENSOR_CRITICAL_OFFLINE_DEVICES = "critical_offline_devices"
SENSOR_LOW_BATTERY_DEVICES_LIST = "low_battery_devices_list"

SUPPORTED_SENSORS: tuple[str, ...] = (
    SENSOR_UNAVAILABLE_DEVICES_LIST,
    SENSOR_UNAVAILABLE_BY_INTEGRATION,
    SENSOR_CRITICAL_OFFLINE_DEVICES,
    SENSOR_LOW_BATTERY_DEVICES_LIST,
)
