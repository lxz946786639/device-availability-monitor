# Device Availability Monitor

Chinese version: [README.md](README.md)

`Device Availability Monitor` is a Home Assistant integration that groups entity states by device and helps you track whether a device is `online`, `degraded`, or `offline`.

## Installation

### HACS

1. Add this repository as a custom repository in HACS and choose `Integration`.
2. Install `device_availability_monitor`.
3. Restart Home Assistant.
4. Go to `Settings -> Devices & services` and add the integration.

### Manual installation

Copy `custom_components/device_availability_monitor/` into your Home Assistant `custom_components/` folder, then restart Home Assistant.

## Features

- Groups entities by device
- Evaluates device health as `online`, `degraded`, or `offline`
- Supports offline strategies:
  - `any`
  - `core`
  - `quorum`
- Detects low battery devices
- Detects flapping devices
- Supports device, entity, integration, and domain exclusions
- Persists runtime state across restarts
- Designed to handle large entity sets with incremental updates

## Entities

### Sensors

The integration creates the following diagnostic sensors:

1. `sensor.unavailable_devices_list`
   - Offline devices list
   - Attributes include device details, critical counts, and scan progress

2. `sensor.unavailable_by_integration`
   - Offline devices grouped by integration

3. `sensor.critical_offline_devices`
   - Critical offline devices list

4. `sensor.low_battery_devices_list`
   - Low battery devices list

5. `sensor.degraded_devices_list`
   - Degraded devices list
   - Reasons may include `low_battery`, `non_core_offline`, and `flap`

6. `sensor.flapping_devices_list`
   - Flapping devices list

### Button

1. `button.reset_device_stats`
   - Name: `Reset Device Stats`
   - Chinese name: `重建设备统计`
   - Icon: `mdi:refresh`
   - Action: calls `device_availability_monitor.reset_stats`

## Service

### `device_availability_monitor.reset_stats`

This service:

- rebuilds the entity and device index
- clears runtime caches
- triggers a full scan
- recalculates offline, degraded, low battery, and flapping results

Use it when the registry changes significantly or when you want to refresh all statistics manually.

## Configuration

### Monitoring options

- `offline_strategy`
  - `any`: any offline entity marks the device offline
  - `core`: only core entities are used, and this is the default
  - `quorum`: the device is offline when more than half of its entities are offline
- `tracked_domains`
- `warning_threshold`
- `critical_threshold`
- `treat_unknown_as_offline`

### Exclusions

- `exclude_domains`
- `exclude_integrations`
- `exclude_devices`
- `exclude_entities`

### Advanced options

- `ui_refresh_interval`
- `cleanup_orphan_after_hours`
- `low_battery_threshold`
- `treat_battery_unavailable_unknown_as_low`

## Implementation Notes

- Scans use version control so older scans cannot overwrite newer results
- Updates that arrive during a scan are queued and the latest state is kept
- Runtime data is stored with Home Assistant `Store` so key state survives restarts
- The following values are restored after restart:
  - `offline_since`
  - `offline_entity_since`
  - `flap_history`
  - `last_recovered_at`
- The integration icon and logo are stored under `brand/`

## Branding Assets

- Integration icon: `custom_components/device_availability_monitor/brand/icon.png`
- Integration logo: `custom_components/device_availability_monitor/brand/logo.png`
- Repository preview image: `logo.png`

## Release Notes

Release note template:

- `.github/release_notes_template.md`

Before publishing a new version, update:

- `custom_components/device_availability_monitor/manifest.json`
- `hacs.json`
- `README.md`

## Compatibility

- Home Assistant `2026.4.0` or later
- HACS supported

