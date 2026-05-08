# 设备可用性监控（Device Availability Monitor）

这是一个 Home Assistant 自定义集成，主要用来把分散在 Home Assistant 里的实体，按“设备”维度重新整理成一份更容易理解的健康状态报表。

很多时候，单个实体是否可用并不能完全说明设备本身的状况。比如一个设备可能只是某个辅助传感器短暂离线，也可能是核心控制实体真的不可用了。这个集成会结合实体状态、设备注册信息和一些稳定性规则，把结果汇总成设备级别的统计，帮助你更快判断哪些设备需要关注。

它会重点关注三类状态：

- `online`：设备整体正常
- `degraded`：设备还能用，但已经出现低电量、部分实体异常或抖动等问题
- `offline`：设备已经满足离线判定条件

English version: [README.en.md](README.en.md)

## 仓库信息

- 仓库地址：[https://github.com/lxz946786639/Device-Availability-Monitor-HA-Integration](https://github.com/lxz946786639/Device-Availability-Monitor-HA-Integration)
- 开源协议：GPLv3（GNU General Public License v3.0），详见 [LICENSE](LICENSE)

适用场景：

- 家里设备很多，单看实体状态已经很难快速判断哪台设备出了问题
- 一个设备下面有多个实体，希望把这些实体汇总成“设备健康”结果来查看
- 想区分“完全离线”和“还能工作但已经不稳定”的设备
- 设备里有电池类实体，希望单独找出低电量设备提前处理
- 某些设备会短时间反复上下线，希望把这类抖动设备单独统计出来
- Home Assistant 里有一些辅助实体离线，但不希望它们直接把整个设备判成离线
- 想在 Lovelace 仪表盘、自动化、模板或告警规则里直接使用这些统计结果
- 需要在 registry 变化后快速重新整理统计，而不是手动逐个排查实体

## 安装

### 方式一：HACS

1. 在 HACS 中添加仓库地址 `https://github.com/lxz946786639/Device-Availability-Monitor-HA-Integration` 为自定义仓库，类别选择 `Integration`
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
- `README.en.md`

## 开源协议

本项目采用 GPLv3（GNU General Public License v3.0）开源协议发布。完整协议文本请查看 [LICENSE](LICENSE)。

## 注意事项

- 该集成不直接轮询设备，只根据 Home Assistant 当前状态和事件做统计
- `reset_stats` 会打断当前扫描并重新计算
- 如果你使用多个 config entry，每个 entry 会创建独立的实体和按钮

## 兼容性

- Home Assistant：`2026.4.0` 及以上
- 支持 HACS 安装
- 支持中文和英文界面
