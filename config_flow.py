"""Config flow for Device Availability Monitor."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.helpers import entity_registry as er, selector

from .const import (
    CONF_CLEANUP_ORPHAN_AFTER_HOURS,
    CONF_CRITICAL_THRESHOLD,
    CONF_EXCLUDE_DEVICES,
    CONF_EXCLUDE_DOMAINS,
    CONF_EXCLUDE_ENTITIES,
    CONF_EXCLUDE_INTEGRATIONS,
    CONF_OFFLINE_STRATEGY,
    CONF_LOW_BATTERY_THRESHOLD,
    CONF_TRACKED_DOMAINS,
    CONF_TREAT_BATTERY_UNAVAILABLE_UNKNOWN_AS_LOW,
    CONF_TREAT_UNKNOWN_AS_OFFLINE,
    CONF_UI_REFRESH_INTERVAL,
    CONF_WARNING_THRESHOLD,
    DEFAULT_CLEANUP_ORPHAN_AFTER_HOURS,
    DEFAULT_CRITICAL_THRESHOLD,
    DEFAULT_OFFLINE_STRATEGY,
    DEFAULT_LOW_BATTERY_THRESHOLD,
    DEFAULT_TRACKED_DOMAINS,
    DEFAULT_TREAT_BATTERY_UNAVAILABLE_UNKNOWN_AS_LOW,
    DEFAULT_TREAT_UNKNOWN_AS_OFFLINE,
    DEFAULT_UI_REFRESH_INTERVAL,
    DEFAULT_WARNING_THRESHOLD,
    DOMAIN,
    get_display_name,
    OFFLINE_STRATEGIES,
    SUPPORTED_TRACKED_DOMAINS,
)


def _default_config() -> dict[str, Any]:
    """Return the default configuration payload."""
    return {
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


def _merged_config(entry: config_entries.ConfigEntry) -> dict[str, Any]:
    """Merge entry data and options into a single config payload."""
    merged = _default_config()
    merged.update(entry.data)
    merged.update(entry.options)
    return merged


def _integration_options(hass) -> list[dict[str, str]]:
    """Build integration selector options from the entity registry."""
    registry = er.async_get(hass)
    integrations = sorted(
        {entry.platform for entry in registry.entities.values() if entry.platform}
    )
    return [{"value": value, "label": value} for value in integrations]


def _domain_options() -> list[dict[str, str]]:
    """Build supported domain options."""
    return [
        {"value": value, "label": value.replace("_", " ").title()}
        for value in SUPPORTED_TRACKED_DOMAINS
    ]


def _offline_strategy_options(language: str | None) -> list[dict[str, str]]:
    """Build offline strategy options with localized labels."""
    is_zh = bool(language and language.lower().startswith("zh"))
    labels = {
        "any": "任意实体离线" if is_zh else "Any entity offline",
        "core": "核心实体离线" if is_zh else "Core entities offline",
        "quorum": "离线过半" if is_zh else "Quorum offline",
    }
    return [{"value": value, "label": labels[value]} for value in OFFLINE_STRATEGIES]


def _normalize_basic_input(user_input: Mapping[str, Any]) -> dict[str, Any]:
    """Normalize the basic monitoring section."""
    return {
        CONF_WARNING_THRESHOLD: int(user_input[CONF_WARNING_THRESHOLD]),
        CONF_CRITICAL_THRESHOLD: int(user_input[CONF_CRITICAL_THRESHOLD]),
        CONF_OFFLINE_STRATEGY: str(user_input[CONF_OFFLINE_STRATEGY]),
        CONF_TREAT_UNKNOWN_AS_OFFLINE: bool(user_input[CONF_TREAT_UNKNOWN_AS_OFFLINE]),
        CONF_TRACKED_DOMAINS: list(user_input[CONF_TRACKED_DOMAINS]),
    }


def _normalize_exclusions_input(user_input: Mapping[str, Any]) -> dict[str, Any]:
    """Normalize the exclusions section."""
    return {
        CONF_EXCLUDE_DEVICES: list(user_input.get(CONF_EXCLUDE_DEVICES, [])),
        CONF_EXCLUDE_ENTITIES: list(user_input.get(CONF_EXCLUDE_ENTITIES, [])),
        CONF_EXCLUDE_INTEGRATIONS: list(user_input.get(CONF_EXCLUDE_INTEGRATIONS, [])),
        CONF_EXCLUDE_DOMAINS: list(user_input.get(CONF_EXCLUDE_DOMAINS, [])),
    }


def _normalize_advanced_input(user_input: Mapping[str, Any]) -> dict[str, Any]:
    """Normalize the advanced section."""
    return {
        CONF_UI_REFRESH_INTERVAL: int(user_input[CONF_UI_REFRESH_INTERVAL]),
        CONF_CLEANUP_ORPHAN_AFTER_HOURS: int(
            user_input[CONF_CLEANUP_ORPHAN_AFTER_HOURS]
        ),
        CONF_LOW_BATTERY_THRESHOLD: int(user_input[CONF_LOW_BATTERY_THRESHOLD]),
        CONF_TREAT_BATTERY_UNAVAILABLE_UNKNOWN_AS_LOW: bool(
            user_input[CONF_TREAT_BATTERY_UNAVAILABLE_UNKNOWN_AS_LOW]
        ),
    }


def _validate_payload(payload: Mapping[str, Any]) -> dict[str, str]:
    """Validate the flow payload."""
    errors: dict[str, str] = {}
    if payload[CONF_CRITICAL_THRESHOLD] < payload[CONF_WARNING_THRESHOLD]:
        errors["base"] = "threshold_order"
    if not payload[CONF_TRACKED_DOMAINS]:
        errors["base"] = "no_domains"
    return errors


def _build_basic_schema(hass, defaults: Mapping[str, Any]) -> vol.Schema:
    """Build the core monitoring schema."""
    return vol.Schema(
        {
            vol.Required(
                CONF_OFFLINE_STRATEGY,
                default=defaults[CONF_OFFLINE_STRATEGY],
            ): selector.SelectSelector(
                selector.SelectSelectorConfig(
                    options=_offline_strategy_options(hass.config.language),
                    multiple=False,
                    mode=selector.SelectSelectorMode.DROPDOWN,
                )
            ),
            vol.Required(
                CONF_TRACKED_DOMAINS,
                default=list(defaults[CONF_TRACKED_DOMAINS]),
            ): selector.SelectSelector(
                selector.SelectSelectorConfig(
                    options=_domain_options(),
                    multiple=True,
                    mode=selector.SelectSelectorMode.DROPDOWN,
                )
            ),
            vol.Required(
                CONF_WARNING_THRESHOLD,
                default=defaults[CONF_WARNING_THRESHOLD],
            ): selector.NumberSelector(
                selector.NumberSelectorConfig(
                    min=0,
                    step=1,
                    mode=selector.NumberSelectorMode.BOX,
                    unit_of_measurement="s",
                )
            ),
            vol.Required(
                CONF_CRITICAL_THRESHOLD,
                default=defaults[CONF_CRITICAL_THRESHOLD],
            ): selector.NumberSelector(
                selector.NumberSelectorConfig(
                    min=0,
                    step=1,
                    mode=selector.NumberSelectorMode.BOX,
                    unit_of_measurement="s",
                )
            ),
            vol.Required(
                CONF_TREAT_UNKNOWN_AS_OFFLINE,
                default=defaults[CONF_TREAT_UNKNOWN_AS_OFFLINE],
            ): selector.BooleanSelector(),
        }
    )


def _build_exclusions_schema(hass, defaults: Mapping[str, Any]) -> vol.Schema:
    """Build the exclusions schema."""
    tracked_domains = list(defaults[CONF_TRACKED_DOMAINS])

    return vol.Schema(
        {
            vol.Required(
                CONF_EXCLUDE_DOMAINS,
                default=list(defaults[CONF_EXCLUDE_DOMAINS]),
            ): selector.SelectSelector(
                selector.SelectSelectorConfig(
                    options=_domain_options(),
                    multiple=True,
                    mode=selector.SelectSelectorMode.DROPDOWN,
                )
            ),
            vol.Required(
                CONF_EXCLUDE_INTEGRATIONS,
                default=list(defaults[CONF_EXCLUDE_INTEGRATIONS]),
            ): selector.SelectSelector(
                selector.SelectSelectorConfig(
                    options=_integration_options(hass),
                    multiple=True,
                    mode=selector.SelectSelectorMode.DROPDOWN,
                )
            ),
            vol.Required(
                CONF_EXCLUDE_DEVICES,
                default=list(defaults[CONF_EXCLUDE_DEVICES]),
            ): selector.DeviceSelector(
                selector.DeviceSelectorConfig(multiple=True)
            ),
            vol.Required(
                CONF_EXCLUDE_ENTITIES,
                default=list(defaults[CONF_EXCLUDE_ENTITIES]),
            ): selector.EntitySelector(
                selector.EntitySelectorConfig(
                    domain=tracked_domains or list(DEFAULT_TRACKED_DOMAINS),
                    multiple=True,
                )
            ),
        }
    )


def _build_advanced_schema(defaults: Mapping[str, Any]) -> vol.Schema:
    """Build the advanced settings schema."""
    return vol.Schema(
        {
            vol.Required(
                CONF_UI_REFRESH_INTERVAL,
                default=defaults[CONF_UI_REFRESH_INTERVAL],
            ): selector.NumberSelector(
                selector.NumberSelectorConfig(
                    min=5,
                    step=1,
                    mode=selector.NumberSelectorMode.BOX,
                    unit_of_measurement="s",
                )
            ),
            vol.Required(
                CONF_CLEANUP_ORPHAN_AFTER_HOURS,
                default=defaults[CONF_CLEANUP_ORPHAN_AFTER_HOURS],
            ): selector.NumberSelector(
                selector.NumberSelectorConfig(
                    min=1,
                    step=1,
                    mode=selector.NumberSelectorMode.BOX,
                    unit_of_measurement="h",
                )
            ),
            vol.Required(
                CONF_LOW_BATTERY_THRESHOLD,
                default=defaults[CONF_LOW_BATTERY_THRESHOLD],
            ): selector.NumberSelector(
                selector.NumberSelectorConfig(
                    min=0,
                    max=100,
                    step=1,
                    mode=selector.NumberSelectorMode.BOX,
                    unit_of_measurement="%",
                )
            ),
            vol.Required(
                CONF_TREAT_BATTERY_UNAVAILABLE_UNKNOWN_AS_LOW,
                default=defaults[CONF_TREAT_BATTERY_UNAVAILABLE_UNKNOWN_AS_LOW],
            ): selector.BooleanSelector(),
        }
    )


class DeviceAvailabilityMonitorConfigFlow(
    config_entries.ConfigFlow,
    domain=DOMAIN,
):
    """Handle a config flow for Device Availability Monitor."""

    VERSION = 1

    def __init__(self) -> None:
        """Initialize the config flow state."""
        self._config: dict[str, Any] = _default_config()

    async def async_step_user(self, user_input: Mapping[str, Any] | None = None):
        """Collect the core monitoring settings."""
        if self._async_current_entries():
            return self.async_abort(reason="already_configured")

        errors: dict[str, str] = {}

        if user_input is not None:
            self._config.update(_normalize_basic_input(user_input))
            errors = _validate_payload(self._config)
            if not errors:
                return await self.async_step_exclusions()

        return self.async_show_form(
            step_id="user",
            data_schema=_build_basic_schema(self.hass, self._config),
            errors=errors,
        )

    async def async_step_exclusions(self, user_input: Mapping[str, Any] | None = None):
        """Collect exclusions for the initial setup."""
        if self._async_current_entries():
            return self.async_abort(reason="already_configured")

        if user_input is not None:
            self._config.update(_normalize_exclusions_input(user_input))
            return await self.async_step_advanced()

        return self.async_show_form(
            step_id="exclusions",
            data_schema=_build_exclusions_schema(self.hass, self._config),
            errors={},
        )

    async def async_step_advanced(self, user_input: Mapping[str, Any] | None = None):
        """Collect the advanced settings for the initial setup."""
        if self._async_current_entries():
            return self.async_abort(reason="already_configured")

        if user_input is not None:
            self._config.update(_normalize_advanced_input(user_input))
            return self.async_create_entry(
                title=get_display_name(self.hass.config.language),
                data=self._config,
            )

        return self.async_show_form(
            step_id="advanced",
            data_schema=_build_advanced_schema(self._config),
            errors={},
        )

    @staticmethod
    def async_get_options_flow(entry: config_entries.ConfigEntry):
        """Return the options flow handler."""
        return DeviceAvailabilityMonitorOptionsFlow(entry)


class DeviceAvailabilityMonitorOptionsFlow(config_entries.OptionsFlow):
    """Handle integration options."""

    def __init__(self, config_entry: config_entries.ConfigEntry) -> None:
        """Initialize the options flow."""
        self._config_entry = config_entry
        self._config: dict[str, Any] = _merged_config(config_entry)

    async def async_step_init(self, user_input: Mapping[str, Any] | None = None):
        """Manage the core monitoring settings."""
        errors: dict[str, str] = {}

        if user_input is not None:
            self._config.update(_normalize_basic_input(user_input))
            errors = _validate_payload(self._config)
            if not errors:
                return await self.async_step_exclusions()

        return self.async_show_form(
            step_id="init",
            data_schema=_build_basic_schema(self.hass, self._config),
            errors=errors,
        )

    async def async_step_exclusions(self, user_input: Mapping[str, Any] | None = None):
        """Manage exclusions."""
        if user_input is not None:
            self._config.update(_normalize_exclusions_input(user_input))
            return await self.async_step_advanced()

        return self.async_show_form(
            step_id="exclusions",
            data_schema=_build_exclusions_schema(self.hass, self._config),
            errors={},
        )

    async def async_step_advanced(self, user_input: Mapping[str, Any] | None = None):
        """Manage advanced settings and save the options."""
        if user_input is not None:
            self._config.update(_normalize_advanced_input(user_input))
            return self.async_create_entry(title="", data=self._config)

        return self.async_show_form(
            step_id="advanced",
            data_schema=_build_advanced_schema(self._config),
            errors={},
        )
