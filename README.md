# 设备可用性监控（Device Availability Monitor）

这是一个用于 Home Assistant 的自定义集成，用来按“设备维度”统计离线、亚健康和低电量状态，并提供适合 Lovelace、自动化和模板消费的诊断型传感器。

当前集成信息：

- 中文名：`设备可用性监控`
- 英文名：`Device Availability Monitor`
- 设备制造商：`noau`
- 集成图标：`brand/icon.png`
- 集成 logo：`brand/logo.png`
- 最低支持 Home Assistant：`2026.4.0`
- 配置方式：`config_flow + options flow`
- 国际化：`zh-Hans` / `en`

## 它解决什么问题

- 不是统计单个 `entity`，而是统计“设备可用性”
- 支持把 `light`、`switch`、`cover`、`fan`、`climate`、`lock` 等设备聚合成设备状态
- 能区分 `online`、`degraded`、`offline` 三态
- 能识别低电量设备和抖动设备
- 支持设备、实体、集成和 domain 排除
- 适合大规模部署，避免全量重建和事件风暴导致卡顿

## 主要特性

- 版本化扫描，避免旧扫描覆盖新状态
- 扫描期间会取消旧任务，并使用新的 `_scan_version` 保证一致性
- `state_changed` 路径保持 O(1) 增量更新
- `pending` 队列按 `entity_id` 去重，始终保留最后状态
- 运行时关键状态通过 Home Assistant `Store` 持久化，重启后可恢复离线起点和 flap 历史
- Snapshot 分为 static / dynamic 两层，避免每次事件都全量 rebuild
- 离线判定支持 `any` / `core` / `quorum`
- 默认离线策略为 `core`
- 亚健康判定包含：
  - 低电量
  - 非核心实体异常
  - flap 抖动
- flap 采用滚动窗口统计，默认 300 秒内达到 3 次即可认为抖动

## 设备状态模型

设备健康状态优先级如下：

1. `offline`
2. `degraded`
3. `online`

说明：

- 只要满足离线策略，设备就进入 `offline`
- 如果未离线，但满足亚健康条件，就进入 `degraded`
- 其它情况为 `online`

## 配置项

首次添加和后续 options flow 都分为 3 步：

1. 基础监控设置
2. 排除项
3. 高级设置

### 基础监控设置

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

## 安装与 HACS

### 直接安装

把整个 `custom_components/device_availability_monitor/` 目录复制到 Home Assistant 的 `custom_components/` 下，然后重启 Home Assistant。

### 通过 HACS 安装

1. 在 HACS 中添加本仓库为自定义仓库，类别选择 `Integration`
2. 安装 `device_availability_monitor`
3. 重启 Home Assistant
4. 到“设置 -> 设备与服务”中添加该集成

仓库根目录已经包含：

- `hacs.json`
- `logo.png`
- `.github/release_notes_template.md`

这些文件能让 HACS 仓库卡片、发布说明和安装体验更完整。

## 扫描与并发控制

实现上使用了版本化扫描模型：

- `self._scan_version: int = 0`
- `self._current_scan_task: asyncio.Task | None = None`

每次启动扫描时：

1. `self._scan_version += 1`
2. 保存当前 `version`
3. 如果已有扫描任务未完成，先 `cancel()`
4. 使用 `hass.async_create_task(self._scan(version))`

扫描循环中会在以下位置检查版本：

- 每个 entity 处理前
- 每批处理后
- snapshot 写入前

这样可以保证旧扫描不会覆盖新状态。

### pending 队列限流

当扫描正在进行时，状态变更不会立即重算，而是进入 pending 队列。

- pending 结构按 `entity_id -> 最新事件` 去重，始终保留最后状态
- 达到 `2000` 条时只记录调试日志，不再清空队列，也不触发全量重扫
- 扫描结束后会按时间顺序补应用这批最新事件

## Snapshot 分层

当前实现把快照拆成两层：

- `self._snapshot_static`
  - `offline_devices`
  - `degraded_devices`
  - `low_battery_devices`
  - `flapping_devices`
  - `by_integration`
  - `offline_strategy`
  - `low_battery_threshold`
  - `treat_battery_unavailable_unknown_as_low`
  - flap 相关常量
- `self._snapshot_dynamic`
  - `offline_count`
  - `critical_count`
  - `warning_count`
  - `degraded_count`
  - `flapping_count`
  - `low_battery_count`
  - 各类总数与截断标记
  - 扫描进度与更新时间

发布到实体时再合并成一个 snapshot，避免每次事件都全量 rebuild。

## 持久化状态

coordinator 使用 Home Assistant `Store` 持久化以下运行时字段：

- `offline_since`
- `offline_entity_since`
- `flap_history`
- `last_recovered_at`

存储 key 采用 config entry 维度隔离，不会改变现有 `entity_id`：

- `device_availability_monitor.<entry_id>.runtime`

恢复流程如下：

1. `async_initialize()` 先从 storage 读取历史数据
2. `_build_indexes()` 建立实体/设备索引
3. 将持久化的 `offline_since`、`offline_entity_since`、`flap_history` 回填到设备运行态
4. 启动扫描后再按当前实体状态修正最终结果

这样可以保证：

- HA 重启后不会丢失当前离线会话的起点
- flap 统计不会因为重启被清零
- `last_recovered_at` 能跨重启继续保留

## 传感器

当前集成会创建 6 个诊断型传感器。

### 1. `sensor.unavailable_devices_list`

用途：

- 输出当前离线设备明细

状态值：

- 离线设备数量

主要属性：

- `devices`
- `devices_total`
- `critical_count`
- `warning_count`
- `devices_truncated`
- `offline_strategy`
- `scan_in_progress`
- `scan_processed_entities`
- `scan_total_entities`
- `updated_at`

### 2. `sensor.unavailable_by_integration`

用途：

- 按集成统计当前离线设备数

状态值：

- 集成数量

主要属性：

- `by_integration`
- `scan_in_progress`
- `scan_processed_entities`
- `scan_total_entities`
- `updated_at`

### 3. `sensor.critical_offline_devices`

用途：

- 输出达到 critical 阈值的设备

主要属性：

- `devices`
- `devices_total`
- `devices_truncated`
- `scan_in_progress`
- `scan_processed_entities`
- `scan_total_entities`
- `updated_at`

### 4. `sensor.low_battery_devices_list`

用途：

- 输出低电量设备明细

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

### 5. `sensor.degraded_devices_list`

用途：

- 输出亚健康设备

状态值：

- 亚健康设备数量

主要属性：

- `devices`
- `devices_total`
- `devices_truncated`
- `low_battery_threshold`
- `flap_threshold`
- `scan_in_progress`
- `scan_processed_entities`
- `scan_total_entities`
- `updated_at`

典型 `reasons` 包含：

- `low_battery`
- `non_core_offline`
- `flap`

### 6. `sensor.flapping_devices_list`

用途：

- 输出在滚动窗口内频繁抖动的设备

状态值：

- 抖动设备数量

主要属性：

- `devices`
- `devices_total`
- `devices_truncated`
- `flap_window_seconds`
- `flap_threshold`
- `scan_in_progress`
- `scan_processed_entities`
- `scan_total_entities`
- `updated_at`

### 常见设备条目结构

```json
{
  "device_id": "abc123",
  "device_name": "Living Room Light",
  "integration": "zha",
  "health_state": "offline",
  "offline_since": "2026-04-30T17:00:00+08:00",
  "offline_duration": 320,
  "severity": "warning",
  "offline_entities": ["light.living_room"],
  "offline_entities_total": 1,
  "offline_entities_truncated": false,
  "last_recovered_at": null
}
```

## `offline_since` 语义

- `offline_since` 只取“当前仍处于 offline 状态”的实体里最早的起始时间
- 如果所有实体都恢复在线，`offline_since` 会被清空
- `core` 模式下只看核心实体，非核心离线不会污染离线起点
- 重启后会优先从 storage 恢复当前离线会话的起点和实体级离线时间

## `degraded` 判定

设备会被标记为 `degraded` 的情况：

1. 低电量低于阈值
2. 非核心实体异常离线
3. flap 次数达到阈值

说明：

- `offline` 的优先级高于 `degraded`
- 如果设备已经离线，不会再显示为 degraded
- `flapping_devices_list` 和 `degraded_devices_list` 是两个独立视图

## Flap 机制

- `flap_history = deque(maxlen=20)`
- `flap_count = int`
- `FLAP_WINDOW_SECONDS = 300`
- `FLAP_THRESHOLD = 3`

当设备健康状态发生变化时，会调用 `_record_flap(device)`，并在窗口外自动裁剪历史。最近 20 条 flap 记录会持久化，重启后可继续统计。

## 使用建议

- 如果主要关注灯、开关、窗帘、空调、锁等真实设备，保持默认 `tracked_domains` 即可
- 如果 `sensor` 类实体波动较大，建议谨慎加入 `tracked_domains`
- 如果某个集成整体不想参与统计，可以直接放进 `exclude_integrations`
- 如果某些电量实体经常返回 `unknown` 或 `unavailable`，可以关闭“将不可用/未知电量视为低电量”

## 服务

### `device_availability_monitor.reset_stats`

用途：

- 重建索引
- 重新扫描当前状态
- 重新计算离线、亚健康、低电量和抖动统计
- 同时清空持久化的离线起点、flap 历史和 `last_recovered_at`

适合：

- registry 大量变化后
- 手动调试
- 怀疑统计结果异常时

## 图形化控制入口

当前集成额外提供一个诊断型按钮：

- `button.reset_device_stats`
  - 显示名称：`Reset Device Stats`
  - 中文名称：`重建设备统计`
  - 图标：`mdi:refresh`
  - 点击后会通过 `device_availability_monitor.reset_stats` 服务触发一次全量重建
  - 日志会提示当前是否正在扫描，并说明该操作会打断当前扫描

这个按钮适合在 Lovelace 仪表盘里放一个显式维护入口，避免用户去服务面板手动调用。

## 性能与稳定性

当前实现满足以下目标：

- `state_changed` 处理路径是 O(1)
- 没有全局扫描，除启动与手动重建外不做全量遍历
- 不使用同步 I/O
- 不阻塞事件循环
- 高频事件不会导致内存无限增长
- pending 事件按 `entity_id` 聚合最新状态，避免重复事件堆积
- 关键运行时字段会持久化，重启后可继续累计离线与 flap 时间
- 旧扫描不会覆盖新扫描结果
- 3000+ entity 的场景下尽量保持平稳

## 备注

- 具体 UI 文案来自 `translations/en.json` 和 `translations/zh-Hans.json`
- HACS 配置位于仓库根目录 `hacs.json`
- 发布说明模板位于 `.github/release_notes_template.md`
- 实际最终显示取决于 Home Assistant 前端语言
- 当前仓库已完成本地语法和资源文件校验，仍建议在真实 Home Assistant 环境中做一次联调验证
