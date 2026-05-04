# 设备可用性监控（Device Availability Monitor）

这是一个用于 Home Assistant 的自定义集成，中文名为“设备可用性监控”，英文名为“Device Availability Monitor”。它用来按“设备维度”统计设备可用性、离线状态和低电量状态，并提供图形化配置、分级告警和适合 Lovelace 使用的传感器输出。

当前集成信息：

- 中文名：`设备可用性监控`
- 英文名：`Device Availability Monitor`
- 设备制造商：`noau`

它重点解决的问题是：

- 不是统计单个 `entity`，而是统计“设备可用性、离线与低电量状态”
- 灯、开关、窗帘、风扇、空调、锁、传感器等设备，只要任意被监控实体变成 `unavailable`，就把整个设备视为不可用
- 支持按集成分类统计，例如 `mqtt`、`zha`、`esphome`
- 支持离线时长、告警分级、低电量监测、设备排除、实体排除和图形化配置
- 提供 `zh-Hans` / `en` 国际化文案

## 版本要求

- 最低支持 Home Assistant：`2026.4.0`
- 配置方式：图形化界面 `config_flow + options flow`
- 单实例集成：是
- 国际化：支持 `zh-Hans` 与 `en`

## 主要功能

- 按 `device` 统计不可用状态，而不是按 `entity`
- 启动后以后台分批方式扫描当前状态，避免大规模系统在初始化时卡死
- 监听状态变化和 registry 变化，自动更新设备离线结果
- 记录每个设备的：
  - `offline_since`
  - `offline_duration`
  - `last_recovered_at`
- 支持 `warning` / `critical` 两级离线阈值
- 支持低电量阈值和低电量设备清单
- 支持排除：
  - 设备
  - 实体
  - 集成
  - domain
- 输出 4 个传感器，适合 Lovelace 卡片、模板和自动化读取
- 提供 `reset_stats` 服务，便于重建索引和重置统计

## 适用范围

本集成优先覆盖以下实体 domain 所属设备：

- `light`
- `switch`
- `cover`
- `fan`
- `climate`
- `lock`
- `sensor`
- `binary_sensor`
- `select`
- `number`
- `media_player`
- `humidifier`
- `water_heater`
- `vacuum`

默认首次启用时，为了降低大规模系统的启动内存压力，优先监控的是：

- `light`
- `switch`
- `cover`
- `fan`
- `climate`
- `lock`
- `media_player`
- `humidifier`
- `water_heater`
- `vacuum`

如果需要，也可以在图形化配置中再手动开启 `sensor`、`binary_sensor`、`select`、`number` 等其它 domain。

核心边界：

- 只统计已经绑定到 `device_registry` 的设备
- 没有 `device_id` 的实体不会进入设备离线统计
- 统计结果是“Home Assistant 设备模型里的设备离线情况”，不是所有 entity 的不可用总表

## 目录结构

```text
custom_components/
  device_availability_monitor/
    __init__.py
    manifest.json
    const.py
    config_flow.py
    coordinator.py
    sensor.py
    services.yaml
    translations/
      en.json
      zh-Hans.json
```

## 安装方式

### 手动安装

1. 将 `custom_components/device_availability_monitor` 复制到 Home Assistant 配置目录下的 `custom_components/`
2. 重启 Home Assistant
3. 进入“设置 -> 设备与服务”
4. 点击“添加集成”
5. 搜索 `设备可用性监控`
6. 按界面提示完成初始化

### HACS

当前仓库还没有加入 HACS 所需的清单文件。

如果后续要发布到 HACS，建议再补充：

- `hacs.json`
- 发布说明
- 版本标签

## 图形化配置

首次添加时可配置：

- 第 1 步：基础监控设置
- `tracked_domains`
- `warning_threshold`
- `critical_threshold`
- `treat_unknown_as_offline`
- 第 2 步：排除项
- `exclude_domains`
- `exclude_integrations`
- `exclude_devices`
- `exclude_entities`
- 第 3 步：高级设置
- `ui_refresh_interval`
- `cleanup_orphan_after_hours`
- `low_battery_threshold`
- `treat_battery_unavailable_unknown_as_low`

在“配置选项”中可继续调整：

- 第 1 步：基础监控设置
- `tracked_domains`
- `warning_threshold`
- `critical_threshold`
- `treat_unknown_as_offline`
- 第 2 步：排除项
- `exclude_domains`
- `exclude_integrations`
- `exclude_devices`
- `exclude_entities`
- 第 3 步：高级设置
- `ui_refresh_interval`
- `cleanup_orphan_after_hours`
- `low_battery_threshold`
- `treat_battery_unavailable_unknown_as_low`

说明：

- 中文界面文案来自 `translations/zh-Hans.json`
- 英文界面文案来自 `translations/en.json`
- Home Assistant 最终显示哪种语言，取决于前端当前语言设置
- 排除设备通过 `DeviceSelector` 选择
- 排除实体通过 `EntitySelector` 选择
- 集成和 domain 通过多选项配置
- 低电量阈值默认 `20%`
- 电量实体不可用或未知时，默认按 `0%` 处理并计入低电量；可在 UI 中关闭
- 不依赖 `configuration.yaml`
- 已提供完整国际化，不再复用同一套文案覆盖所有语言

## 默认行为

- 设备下任意一个被监控实体状态为 `unavailable`，设备视为离线
- 默认不会将 `unknown` 视为离线，可在 UI 中手动开启
- 首次启动全量扫描时，不会无条件跳过 `unknown`；是否计入离线由 `treat_unknown_as_offline` 决定
- 低电量监测默认将电量实体的 `unavailable` / `unknown` 视为 `0%`
- 可在 UI 中关闭“把不可用/未知电量视为低电量”
- 只有当设备下所有被监控实体都恢复正常，设备才恢复在线
- 离线起点 `offline_since` 会优先采用实体当前状态的 `last_changed`，设备级在同一轮离线会话里只会前移，不会因为部分实体恢复而后移
- 离线时长通过本地定时刷新更新，不访问远程设备
- 为避免状态属性过大，详细离线设备列表会做数量截断，并在 attributes 中标记是否被截断
- 首次状态扫描改为后台分批执行，运行期更新尽量采用事件驱动
- 低电量监测复用同一套后台分批扫描，不会额外引入同步全量遍历
- 4 个摘要传感器的 `state` 都是数值，详细列表和分类统计放在 attributes 中
- 这 4 个摘要传感器都被标记为诊断类实体
- 传感器名称通过本地化翻译提供，不再在代码里硬编码中文

## 传感器输出

本集成会创建 4 个传感器。

注意：

- 实际 `entity_id` 由 Home Assistant 根据实体名称和唯一 ID 自动生成
- 如果系统中已有重名实体，最终 `entity_id` 可能会带后缀

### 1. 不可用设备列表

用途：

- 输出当前离线设备明细

状态值：

- 设备数量的数值，例如 `3`

主要属性：

- `devices`
- `devices_total`
- `critical_count`
- `warning_count`
- `devices_truncated`
- `updated_at`

`devices` 中每一项包含类似字段：

```json
{
  "device_id": "abc123",
  "device_name": "Living Room Light",
  "integration": "zha",
  "domains": ["light"],
  "offline_since": "2026-04-30T17:00:00+08:00",
  "offline_duration": 320,
  "severity": "warning",
  "offline_entities": ["light.living_room"],
  "last_recovered_at": null
}
```

### 2. 按集成统计不可用设备

用途：

- 按集成统计当前离线设备数

状态值：

- 集成数量的数值，例如 `2`

主要属性：

- `by_integration`
- `updated_at`

### 3. 严重离线设备

用途：

- 输出达到 `critical` 阈值的设备数量和明细

筛选规则：

- 设备下任意一个被监控实体变为 `unavailable` 时，设备会先进入离线集合
- 如果已开启“将 `unknown` 视为离线”，那么 `unknown` 也会触发离线
- `offline_since` 优先取离线实体状态自身的 `last_changed`，设备级在同一轮离线会话里只会前移，不会因为部分实体恢复而后移
- 从 `offline_since` 开始累计离线时长
- 当 `offline_duration >= critical_threshold` 时，该设备进入“严重离线设备”
- 默认 `critical_threshold` 为 `600` 秒，可在图形化界面调整

主要属性：

- `devices`
- `updated_at`

### 4. 低电量设备列表

用途：

- 输出当前低电量设备明细

状态值：

- 低电量设备数量的数值，例如 `5`

主要属性：

- `devices`
- `devices_total`
- `devices_truncated`
- `low_battery_threshold`
- `treat_battery_unavailable_unknown_as_low`
- `scan_in_progress`
- `scan_processed_entities`
- `scan_total_entities`
- `updated_at`

`devices` 中每一项包含类似字段：

```json
{
  "device_id": "abc123",
  "device_name": "Kitchen Lock",
  "integration": "zha",
  "battery_percent": 18,
  "battery_source_entity_id": "sensor.kitchen_lock_battery",
  "battery_entities": ["sensor.kitchen_lock_battery"],
  "battery_entities_total": 1,
  "battery_entities_truncated": false
}
```

筛选规则：

- 设备会先收集所有具备电量语义的实体，再取最低电量值
- 默认低于 `20%` 的设备进入低电量列表
- 电量实体处于 `unavailable` 或 `unknown` 时，默认按 `0%` 处理并计入低电量
- 可以在图形化界面里关闭“把不可用/未知电量视为低电量”的选项
- 低电量列表同样通过后台分批扫描和事件驱动更新，不会阻塞 Home Assistant 主线程

## 服务

### `device_availability_monitor.reset_stats`

用途：

- 重建 entity/device 映射
- 重新扫描当前状态
- 按当前状态重建离线记录和低电量记录

适用场景：

- 设备 registry 发生大量变化后
- 手动调试时
- 怀疑统计结果异常时

## 使用建议

- 如果你的目标是重点关注离线灯、开关、窗帘等设备，建议保留默认的 `tracked_domains`
- 如果某些 `sensor` 类实体波动大、经常 `unknown`，可以：
  - 保持 `treat_unknown_as_offline` 为关闭
  - 或不要把 `sensor` 加入 `tracked_domains`
  - 或直接把对应实体或设备排除
- 如果某些电量实体经常返回 `unknown` / `unavailable`，可以在 UI 中关闭“把不可用/未知电量视为低电量”
- 如果某个集成整体不想参与统计，例如 `mqtt`，可以直接加入 `exclude_integrations`

## 已知限制

- 没有 `device_id` 的实体不会被统计为“设备离线”
- `group`、`template`、`input_*` 等逻辑实体不属于本集成的重点监控范围
- 当前仓库只做了本地语法和资源文件校验，尚未包含完整的 Home Assistant 集成测试用例
- 低电量监测只识别具备电量语义的实体，主要是 `battery` 设备类传感器

## 开发与验证

当前仓库已完成：

- 自定义集成目录结构
- `config_flow` 多步表单
- `options flow` 多步表单
- `zh-Hans` / `en` 国际化文案
- 设备级离线聚合 coordinator
- 4 个传感器
- `reset_stats` 服务
- 本地 Python 语法编译检查
- `manifest.json` / `translations/en.json` / `translations/zh-Hans.json` JSON 解析检查

建议在真实 Home Assistant `2026.4.0` 环境中进一步验证：

- 集成添加流程
- options flow 更新后自动 reload
- 设备排除和实体排除是否符合预期
- registry 变更后的重建行为
- Lovelace 展示和模板访问体验

## 许可证

当前仓库尚未附带许可证文件。

如果项目计划公开发布，建议补充一个明确的 `LICENSE` 文件。
