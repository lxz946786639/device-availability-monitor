# 设备可用性监控（Device Availability Monitor）

这是一个 Home Assistant 自定义集成，用来按“设备”维度统计离线、亚健康和低电量状态。

适用场景：

- 想把多个实体汇总成一个设备健康状态
- 想区分 `online`、`degraded`、`offline`
- 想查看低电量设备、抖动设备和严重离线设备
- 想在 Lovelace、自动化、模板中直接使用统计结果

## 基本信息

- 中文名：`设备可用性监控`
- 英文名：`Device Availability Monitor`
- 设备制造商：`noau`
- 图标：`brand/icon.png`
- Logo：`brand/logo.png`
- 最低支持 Home Assistant：`2026.4.0`
- 配置方式：`config_flow + options flow`
- 国际化：`zh-Hans` / `en`

## 安装

### 方式一：HACS

1. 在 HACS 中添加本仓库为自定义仓库，类别选择 `Integration`
2. 安装 `device_availability_monitor`
3. 重启 Home Assistant
4. 到“设置 -> 设备与服务”中添加集成

仓库根目录包含：

- `hacs.json`
- `logo.png`
- `.github/release_notes_template.md`

### 方式二：手动安装

把 `custom_components/device_availability_monitor/` 目录复制到 Home Assistant 的 `custom_components/` 下，然后重启 Home Assistant。

## 功能

- 按设备统计离线状态
- 支持 `online`、`degraded`、`offline` 三态
- 支持离线策略：
  - `any`
  - `core`
  - `quorum`
- 支持低电量检测
- 支持 flap 抖动检测
- 支持设备、实体、集成和 domain 排除
- 支持重启后恢复离线时间和 flap 历史
- 支持大规模实体场景，避免频繁全量重建

## 状态说明

设备健康状态优先级：

1. `offline`
2. `degraded`
3. `online`

说明：

- 满足离线条件时，设备显示为 `offline`
- 未离线但满足亚健康条件时，设备显示为 `degraded`
- 其他情况显示为 `online`

## 可用实体

### 传感器

当前集成会创建 6 个诊断型传感器：

1. `sensor.unavailable_devices_list`
   - 离线设备列表
   - 属性包含离线设备明细、严重数量和扫描进度

2. `sensor.unavailable_by_integration`
   - 按集成统计离线设备数
   - 属性包含 `by_integration`

3. `sensor.critical_offline_devices`
   - 严重离线设备列表

4. `sensor.low_battery_devices_list`
   - 低电量设备列表

5. `sensor.degraded_devices_list`
   - 亚健康设备列表
   - 原因包括：
     - `low_battery`
     - `non_core_offline`
     - `flap`

6. `sensor.flapping_devices_list`
   - 抖动设备列表

### 按钮

1. `button.reset_device_stats`
   - 显示名称：`Reset Device Stats`
   - 中文名称：`重建设备统计`
   - 图标：`mdi:refresh`
   - 作用：通过服务 `device_availability_monitor.reset_stats` 触发一次全量重建

## 服务

### `device_availability_monitor.reset_stats`

作用：

- 重建实体和设备索引
- 清空运行时缓存
- 触发全量扫描
- 重新计算离线、亚健康、低电量和抖动统计

适合在以下情况下使用：

- registry 发生较大变化后
- 数据看起来不一致时
- 需要手动重新整理统计结果时

## 配置项

### 基础监控

- `offline_strategy`
  - `any`：任意实体离线就算设备离线
  - `core`：只看核心实体，默认值
  - `quorum`：离线实体过半才算设备离线
- `tracked_domains`
- `warning_threshold`
- `critical_threshold`
- `treat_unknown_as_offline`

### 排除项

- `exclude_domains`
- `exclude_integrations`
- `exclude_devices`
- `exclude_entities`

### 高级设置

- `ui_refresh_interval`
- `cleanup_orphan_after_hours`
- `low_battery_threshold`
- `treat_battery_unavailable_unknown_as_low`

## 实现说明

- 扫描使用版本号控制，避免旧扫描覆盖新结果
- `state_changed` 路径是增量处理，不做全局遍历
- 扫描期间的更新会进入 pending 队列，并保留最后状态
- 关键运行时数据会通过 Home Assistant `Store` 持久化
- 重启后会恢复 `offline_since`、`offline_entity_since`、`flap_history` 和 `last_recovered_at`
- 集成图标和 Logo 已放在 `brand/` 目录下

## 图标与品牌资源

- 集成图标：`custom_components/device_availability_monitor/brand/icon.png`
- 集成 Logo：`custom_components/device_availability_monitor/brand/logo.png`
- 仓库预览图：`logo.png`

## 发版说明

发版说明模板位于：

- `.github/release_notes_template.md`

如果要发布新版本，建议同步更新：

- `custom_components/device_availability_monitor/manifest.json`
- `hacs.json`
- `README.md`

## 注意事项

- 该集成不直接轮询设备，只根据 Home Assistant 当前状态和事件做统计
- `reset_stats` 会打断当前扫描并重新计算
- 如果你使用多个 config entry，每个 entry 会创建独立的实体和按钮

## 兼容性

- Home Assistant：`2026.4.0` 及以上
- 支持 HACS 安装
- 支持中文和英文界面

