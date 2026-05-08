# Device Availability Monitor

[![HACS Custom](https://img.shields.io/badge/HACS-Custom-orange.svg)](https://hacs.xyz/docs/faq/custom_repositories/)
[![GitHub release](https://img.shields.io/github/v/release/lxz946786639/Device-Availability-Monitor-HA-Integration?display_name=tag)](https://github.com/lxz946786639/Device-Availability-Monitor-HA-Integration/releases)
[![License: GPL v3](https://img.shields.io/badge/License-GPLv3-blue.svg)](LICENSE)

Device Availability Monitor is a Home Assistant custom integration that groups entity states by device and helps you understand whether each device is `online`, `degraded`, or `offline`.

Many Home Assistant devices expose multiple entities. A single auxiliary entity becoming unavailable does not always mean the whole device is down, while core entity failures, low battery, and frequent state flapping often need attention. This integration combines entity states, the device registry, and stability rules to produce device-level health statistics for dashboards, automations, templates, and alerts.

Chinese version: [README.md](README.md)

Repository: [https://github.com/lxz946786639/Device-Availability-Monitor-HA-Integration](https://github.com/lxz946786639/Device-Availability-Monitor-HA-Integration)

## Features

- Groups Home Assistant entity states by device
- Reports device health as `online`, `degraded`, or `offline`
- Supports `any`, `core`, and `quorum` offline strategies
- Detects low battery devices
- Detects flapping devices that repeatedly go offline and online in a short period
- Supports exclusions by domain, integration, device, and entity
- Restores offline time, per-entity offline time, flap history, and last recovery time after restart
- Uses incremental updates for large Home Assistant installations
- Provides diagnostic sensors for dashboards, automations, templates, and alerts
- Provides a reset button and service to rebuild device statistics

## Installation

### HACS custom repository (recommended)

1. Open HACS.
2. Go to `Integrations`.
3. Open the top-right menu and choose `Custom repositories`.
4. Add this repository URL:

   ```text
   https://github.com/lxz946786639/Device-Availability-Monitor-HA-Integration
   ```

5. Select `Integration` as the category.
6. Search for and install `Device Availability Monitor`.
7. Restart Home Assistant.
8. Go to `Settings -> Devices & services -> Add integration`, then search for and add `Device Availability Monitor`.

### Manual installation

1. Download or clone this repository.
2. Copy `custom_components/device_availability_monitor/` into the `custom_components/` directory inside your Home Assistant configuration folder.
3. Restart Home Assistant.
4. Go to `Settings -> Devices & services -> Add integration`, then search for and add `Device Availability Monitor`.

Example directory layout:

```text
config/
+-- custom_components/
    +-- device_availability_monitor/
        +-- __init__.py
        +-- manifest.json
        +-- config_flow.py
        +-- coordinator.py
        +-- sensor.py
        +-- button.py
```

## Configuration

The integration is configured through the Home Assistant UI. No manual `configuration.yaml` entry is required.

### Core monitoring

| Option | Default | Description |
| --- | --- | --- |
| `offline_strategy` | `core` | Strategy used to decide whether a device is offline |
| `tracked_domains` | `light`, `switch`, `cover`, `fan`, `climate`, `lock`, `media_player`, `humidifier`, `water_heater`, `vacuum` | Entity domains included in device availability monitoring |
| `warning_threshold` | `60` seconds | A device becomes warning after being offline for this long |
| `critical_threshold` | `600` seconds | A device becomes critical after being offline for this long |
| `treat_unknown_as_offline` | `false` | Whether `unknown` should be treated as offline |

Offline strategy behavior:

- `any`: any offline entity marks the whole device as offline
- `core`: only core device domains are used for offline detection, and this is the default
- `quorum`: the device is offline when more than half of its entities are offline

### Exclusions

| Option | Description |
| --- | --- |
| `exclude_domains` | Exclude entire entity domains |
| `exclude_integrations` | Exclude specific integrations such as `mqtt`, `zha`, or `esphome` |
| `exclude_devices` | Exclude specific devices |
| `exclude_entities` | Exclude specific entities |

### Advanced settings

| Option | Default | Description |
| --- | --- | --- |
| `ui_refresh_interval` | `60` seconds | UI refresh interval for offline duration and severity display |
| `cleanup_orphan_after_hours` | `24` hours | Retention time for recovered records whose registry device no longer exists |
| `low_battery_threshold` | `20` | Battery percentage threshold for low battery detection |
| `treat_battery_unavailable_unknown_as_low` | `true` | Whether battery entities in `unavailable` or `unknown` state should be treated as low battery |

## Entities

Entity IDs may vary depending on the Home Assistant entity registry. The entity keys below are stable internal identifiers, while the example entity IDs are common defaults.

### Sensors

| Entity key | Common entity ID | State | Description |
| --- | --- | --- | --- |
| `unavailable_devices_list` | `sensor.device_availability_monitor_unavailable_devices_list` | Offline device count | Attributes include offline device details, warning/critical counts, and scan progress |
| `unavailable_by_integration` | `sensor.device_availability_monitor_unavailable_by_integration` | Number of integrations with offline devices | Attributes include `by_integration` statistics |
| `critical_offline_devices` | `sensor.device_availability_monitor_critical_offline_devices` | Critical offline device count | Attributes include critical offline device details |
| `low_battery_devices_list` | `sensor.device_availability_monitor_low_battery_devices_list` | Low battery device count | Attributes include low battery device details and threshold |
| `degraded_devices_list` | `sensor.device_availability_monitor_degraded_devices_list` | Degraded device count | Reasons include `low_battery`, `non_core_offline`, and `flap` |
| `flapping_devices_list` | `sensor.device_availability_monitor_flapping_devices_list` | Flapping device count | Attributes include flap window and threshold |

### Button

| Entity key | Common entity ID | Description |
| --- | --- | --- |
| `reset_device_stats` | `button.device_availability_monitor_reset_device_stats` | Triggers a full rebuild and recalculation |

## Service

### `device_availability_monitor.reset_stats`

This service will:

- Rebuild the entity and device indexes
- Clear runtime caches
- Trigger a full scan
- Recalculate offline, degraded, low battery, and flapping statistics

Use it when:

- The Home Assistant registry changed significantly
- Many devices were added, removed, or renamed
- Dashboard statistics look inconsistent
- You changed exclusions or monitored domains and want an immediate refresh

## Usage Examples

### Lovelace entities card

```yaml
type: entities
title: Device Health
entities:
  - entity: sensor.device_availability_monitor_unavailable_devices_list
  - entity: sensor.device_availability_monitor_critical_offline_devices
  - entity: sensor.device_availability_monitor_low_battery_devices_list
  - entity: sensor.device_availability_monitor_degraded_devices_list
  - entity: sensor.device_availability_monitor_flapping_devices_list
  - entity: button.device_availability_monitor_reset_device_stats
```

### Critical offline notification automation

```yaml
alias: Critical offline device alert
trigger:
  - platform: numeric_state
    entity_id: sensor.device_availability_monitor_critical_offline_devices
    above: 0
action:
  - service: notify.notify
    data:
      title: Critical offline devices
      message: >
        There are {{ states('sensor.device_availability_monitor_critical_offline_devices') }}
        devices in critical offline state.
```

## How It Works

- The integration does not actively poll physical devices. It calculates results from Home Assistant states, events, and registry data.
- A full scan runs when the integration first loads.
- `state_changed` events are handled incrementally to avoid scanning all entities on every update.
- Updates that arrive during a scan are queued and the latest state for each entity is kept.
- Scan versions prevent older scans from overwriting newer results.
- Runtime data is persisted with Home Assistant `Store`.
- After restart, the integration restores `offline_since`, `offline_entity_since`, `flap_history`, and `last_recovered_at`.

## Troubleshooting

### The integration does not appear in HACS

- Make sure the custom repository URL is `https://github.com/lxz946786639/Device-Availability-Monitor-HA-Integration`
- Make sure the repository category is `Integration`
- Reload HACS, then restart Home Assistant if needed

### No entities appear after installation

- Make sure the integration has been added from `Settings -> Devices & services`
- Make sure your Home Assistant version is `2026.4.0` or later
- Try calling `device_availability_monitor.reset_stats`

### Too many devices are reported offline

- Start with the default `core` offline strategy
- Check whether too many `sensor` or `binary_sensor` domains are enabled
- Use `exclude_domains`, `exclude_integrations`, `exclude_devices`, or `exclude_entities` to remove noisy sources
- Adjust `warning_threshold` and `critical_threshold` for your environment

### Low battery results are unexpected

- Check `low_battery_threshold`
- Disable `treat_battery_unavailable_unknown_as_low` if you do not want `unavailable` or `unknown` battery entities to appear in the low battery list

## Updating

### HACS update

1. Open `Device Availability Monitor` in HACS.
2. Check for updates or reload the repository information.
3. Install the new version if one is available.
4. Restart Home Assistant after the update.

### Manual update

1. Download the latest version.
2. Replace `custom_components/device_availability_monitor/`.
3. Restart Home Assistant.

## Compatibility

- Home Assistant `2026.4.0` or later
- HACS custom repository or manual installation
- Chinese and English UI text

## Contributing

Issues and pull requests are welcome:

[https://github.com/lxz946786639/Device-Availability-Monitor-HA-Integration/issues](https://github.com/lxz946786639/Device-Availability-Monitor-HA-Integration/issues)

## License

This project is licensed under the GPLv3 (GNU General Public License v3.0). See [LICENSE](LICENSE) for the full license text.

## Author

- GitHub: [@lxz946786639](https://github.com/lxz946786639)
