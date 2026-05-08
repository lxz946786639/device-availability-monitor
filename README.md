# 设备可用性监控

[![HACS Custom](https://img.shields.io/badge/HACS-Custom-orange.svg)](https://hacs.xyz/docs/faq/custom_repositories/)
[![GitHub release](https://img.shields.io/github/v/release/lxz946786639/Device-Availability-Monitor-HA-Integration?display_name=tag)](https://github.com/lxz946786639/Device-Availability-Monitor-HA-Integration/releases)
[![License: GPL v3](https://img.shields.io/badge/License-GPLv3-blue.svg)](LICENSE)

Device Availability Monitor 是一个 Home Assistant 自定义集成，用来把分散在 Home Assistant 里的实体状态按“设备”维度重新汇总，帮助你快速判断设备是否处于 `online`、`degraded` 或 `offline` 状态。

很多设备下面会挂载多个实体。单个辅助实体离线并不一定代表设备不可用，而核心实体不可用、低电量、频繁上下线等情况又需要及时关注。这个集成会结合实体状态、设备注册表和稳定性规则，生成更适合日常排查和自动化告警的设备健康统计。

English version: [README.en.md](README.en.md)

仓库地址：[https://github.com/lxz946786639/Device-Availability-Monitor-HA-Integration](https://github.com/lxz946786639/Device-Availability-Monitor-HA-Integration)

## 功能特点

- 按设备维度汇总 Home Assistant 实体状态
- 支持 `online`、`degraded`、`offline` 三种设备健康状态
- 支持 `any`、`core`、`quorum` 三种离线判定策略
- 支持低电量设备检测
- 支持设备抖动检测，用于识别短时间反复上下线的设备
- 支持按 domain、集成、设备和实体排除监控对象
- 支持重启后恢复离线时间、实体离线时间、抖动历史和最近恢复时间
- 支持增量更新，适合实体数量较多的 Home Assistant 实例
- 提供诊断传感器，可用于仪表盘、自动化、模板和告警规则
- 提供重建设备统计按钮和服务

## 安装

### HACS 自定义仓库安装（推荐）

1. 打开 HACS。
2. 进入 `Integrations`。
3. 点击右上角菜单，选择 `Custom repositories`。
4. 在仓库地址中填入：

   ```text
   https://github.com/lxz946786639/Device-Availability-Monitor-HA-Integration
   ```

5. 类别选择 `Integration`。
6. 搜索并安装 `Device Availability Monitor`。
7. 重启 Home Assistant。
8. 进入 `设置 -> 设备与服务 -> 添加集成`，搜索并添加 `设备可用性监控`。

### 手动安装

1. 下载或克隆本仓库。
2. 将 `custom_components/device_availability_monitor/` 复制到 Home Assistant 配置目录下的 `custom_components/`。
3. 重启 Home Assistant。
4. 进入 `设置 -> 设备与服务 -> 添加集成`，搜索并添加 `设备可用性监控`。

目录结构示例：

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

## 配置

集成通过 Home Assistant UI 配置，不需要手动编辑 `configuration.yaml`。

### 基础监控

| 配置项 | 默认值 | 说明 |
| --- | --- | --- |
| `offline_strategy` | `core` | 设备离线判定策略 |
| `tracked_domains` | `light`, `switch`, `cover`, `fan`, `climate`, `lock`, `media_player`, `humidifier`, `water_heater`, `vacuum` | 参与设备可用性统计的实体域 |
| `warning_threshold` | `60` 秒 | 设备连续离线达到该时间后标记为 warning |
| `critical_threshold` | `600` 秒 | 设备连续离线达到该时间后标记为 critical |
| `treat_unknown_as_offline` | `false` | 是否将 `unknown` 状态视为离线 |

离线策略说明：

- `any`：任意实体离线就将设备判定为离线
- `core`：只使用核心设备域进行离线判定，默认策略
- `quorum`：离线实体超过半数时将设备判定为离线

### 排除项

| 配置项 | 说明 |
| --- | --- |
| `exclude_domains` | 排除整个实体域 |
| `exclude_integrations` | 排除指定集成，例如 `mqtt`、`zha`、`esphome` |
| `exclude_devices` | 排除指定设备 |
| `exclude_entities` | 排除指定实体 |

### 高级设置

| 配置项 | 默认值 | 说明 |
| --- | --- | --- |
| `ui_refresh_interval` | `60` 秒 | 界面刷新间隔，仅影响离线时长和告警等级显示 |
| `cleanup_orphan_after_hours` | `24` 小时 | 已不存在于 registry 的恢复记录保留时间 |
| `low_battery_threshold` | `20` | 低电量阈值，低于该百分比会进入低电量列表 |
| `treat_battery_unavailable_unknown_as_low` | `true` | 是否将电量实体的 `unavailable` 或 `unknown` 状态按低电量处理 |

## 可用实体

实体 ID 可能会受 Home Assistant 实体注册表命名影响。下表中的“实体 key”是集成内部稳定标识，常见实体 ID 仅作参考。

### 传感器

| 实体 key | 常见实体 ID | 状态值 | 说明 |
| --- | --- | --- | --- |
| `unavailable_devices_list` | `sensor.device_availability_monitor_unavailable_devices_list` | 离线设备数量 | 属性包含离线设备明细、warning/critical 数量和扫描进度 |
| `unavailable_by_integration` | `sensor.device_availability_monitor_unavailable_by_integration` | 出现离线设备的集成数量 | 属性包含 `by_integration` 统计 |
| `critical_offline_devices` | `sensor.device_availability_monitor_critical_offline_devices` | 严重离线设备数量 | 属性包含严重离线设备明细 |
| `low_battery_devices_list` | `sensor.device_availability_monitor_low_battery_devices_list` | 低电量设备数量 | 属性包含低电量设备明细和阈值 |
| `degraded_devices_list` | `sensor.device_availability_monitor_degraded_devices_list` | 亚健康设备数量 | 原因包括 `low_battery`、`non_core_offline`、`flap` |
| `flapping_devices_list` | `sensor.device_availability_monitor_flapping_devices_list` | 抖动设备数量 | 属性包含抖动窗口和阈值 |

### 按钮

| 实体 key | 常见实体 ID | 说明 |
| --- | --- | --- |
| `reset_device_stats` | `button.device_availability_monitor_reset_device_stats` | 触发一次全量重建和重新统计 |

## 服务

### `device_availability_monitor.reset_stats`

该服务会：

- 重建实体和设备索引
- 清空运行时缓存
- 触发一次全量扫描
- 重新计算离线、亚健康、低电量和抖动统计

适合在以下场景手动调用：

- Home Assistant registry 发生较大变化后
- 新增、删除或重命名大量设备后
- 仪表盘统计看起来不一致时
- 调整排除项或监控范围后希望立即刷新结果

## 使用示例

### Lovelace 实体卡片

```yaml
type: entities
title: 设备健康状态
entities:
  - entity: sensor.device_availability_monitor_unavailable_devices_list
  - entity: sensor.device_availability_monitor_critical_offline_devices
  - entity: sensor.device_availability_monitor_low_battery_devices_list
  - entity: sensor.device_availability_monitor_degraded_devices_list
  - entity: sensor.device_availability_monitor_flapping_devices_list
  - entity: button.device_availability_monitor_reset_device_stats
```

### 严重离线告警自动化

```yaml
alias: 设备严重离线告警
trigger:
  - platform: numeric_state
    entity_id: sensor.device_availability_monitor_critical_offline_devices
    above: 0
action:
  - service: notify.notify
    data:
      title: 设备严重离线
      message: >
        当前有 {{ states('sensor.device_availability_monitor_critical_offline_devices') }}
        个设备处于严重离线状态。
```

## 工作方式

- 集成不会主动轮询真实设备，只根据 Home Assistant 当前状态、事件和 registry 信息进行统计
- 首次加载会进行一次全量扫描
- `state_changed` 事件会走增量更新，避免每次都遍历全部实体
- 扫描期间的新事件会进入 pending 队列，并保留每个实体的最后状态
- 上一份完整统计结果会持久化保存，启动或 registry 重建扫描期间会优先保留并展示这份结果
- 扫描进度通过 `scan_in_progress`、`scan_processed_entities` 和 `scan_total_entities` 属性展示
- 扫描完成后才会一次性替换公开统计结果，避免启动期或 registry 更新风暴导致传感器数值反复归零
- 扫描使用版本号控制，避免旧扫描覆盖新结果
- 运行时数据通过 Home Assistant `Store` 持久化
- 重启后会恢复 `offline_since`、`offline_entity_since`、`flap_history` 和 `last_recovered_at`

## 故障排除

### HACS 中找不到集成

- 确认自定义仓库地址填写为 `https://github.com/lxz946786639/Device-Availability-Monitor-HA-Integration`
- 确认仓库类别选择的是 `Integration`
- 重新加载 HACS，必要时重启 Home Assistant

### 安装后没有实体

- 确认已经在 `设置 -> 设备与服务` 中添加集成
- 确认 Home Assistant 版本不低于 `2026.4.0`
- 尝试调用 `device_availability_monitor.reset_stats`

### 启动时传感器暂时没有新数值

- 首次安装或清空统计后没有上一份完整快照，首轮扫描完成前传感器可能暂时没有数值
- 正常重启或 registry 重建时，集成会恢复并保留上一份完整统计结果，扫描完成后再更新为新结果
- 可在传感器属性中查看 `scan_in_progress`、`scan_processed_entities` 和 `scan_total_entities` 判断是否仍在扫描

### 离线设备数量过多

- 优先使用默认的 `core` 离线策略
- 检查是否启用了过多 `sensor` 或 `binary_sensor` 类实体域
- 使用 `exclude_domains`、`exclude_integrations`、`exclude_devices` 或 `exclude_entities` 排除噪声来源
- 根据设备环境调整 `warning_threshold` 和 `critical_threshold`

### 低电量结果不符合预期

- 检查 `low_battery_threshold`
- 如果不希望 `unavailable` 或 `unknown` 的电量实体进入低电量列表，关闭 `treat_battery_unavailable_unknown_as_low`

## 更新版本

### HACS 更新

1. 在 HACS 中进入 `Device Availability Monitor`。
2. 点击检查更新或重新加载仓库信息。
3. 如果有新版本，点击更新。
4. 更新完成后重启 Home Assistant。

### 手动更新

1. 下载最新版本。
2. 替换 `custom_components/device_availability_monitor/` 目录。
3. 重启 Home Assistant。

## 兼容性

- Home Assistant：`2026.4.0` 或以上
- 安装方式：HACS 自定义仓库或手动安装
- 界面语言：中文和英文

## 贡献

欢迎通过 GitHub Issues 和 Pull Requests 反馈问题、提出建议或贡献代码：

[https://github.com/lxz946786639/Device-Availability-Monitor-HA-Integration/issues](https://github.com/lxz946786639/Device-Availability-Monitor-HA-Integration/issues)

## 开源协议

本项目采用 GPLv3（GNU General Public License v3.0）开源协议发布。完整协议文本请查看 [LICENSE](LICENSE)。

## 作者

- GitHub：[@lxz946786639](https://github.com/lxz946786639)
