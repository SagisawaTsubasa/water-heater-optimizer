# Water Heater Optimizer

> 根据自来水温度动态计算燃气热水器最佳出口温度，让恒温淋浴全年稳定。  
> Dynamically calculates the optimal gas water heater outlet temperature based on tap water temperature for stable thermostatic showers year-round.

**Home Assistant version:** 26.1.3  
**Programmer:** Kimi (Moonshot AI)  
**License:** MIT

---

## 安装 / Installation

### HACS (推荐 / Recommended)
1. 在 HACS 中添加自定义仓库 `https://github.com/SagisawaTsubasa/water-heater-optimizer`，类别选**集成 / Integration**。  
   Add `https://github.com/SagisawaTsubasa/water-heater-optimizer` as a custom repository in HACS, category **Integration**.
2. 安装 **Water Heater Optimizer**。  
   Install **Water Heater Optimizer**.
3. 重启 Home Assistant。  
   Restart Home Assistant.

### 手动 / Manual
1. 将 `custom_components/water_heater_optimizer` 复制到 Home Assistant 的 `custom_components` 目录（覆盖旧版）。  
   Copy the `custom_components/water_heater_optimizer` folder into your Home Assistant `custom_components` directory (overwrite the old version).
2. 从 0.3.0 升级时，删除旧目录残留的 `services.yaml`（0.4.0 已移除该文件与服务）。  
   When upgrading from 0.3.0, delete the leftover `services.yaml` in the old folder (removed in 0.4.0).
3. 从 0.4.0 升级时，删除旧目录残留的 `web.py` 与 `static/` 子目录（0.5.0 已移除文羽面板页）。  
   When upgrading from 0.4.0, delete the leftover `web.py` and `static/` folder in the old directory (the FumihaHub panel page was removed in 0.5.0).
4. 重启 Home Assistant。  
   Restart Home Assistant.

---

## 配置 / Configuration

前往 **设置 → 设备与服务 → 添加集成**，搜索 **Water Heater Optimizer**。  
Go to **Settings → Devices & Services → Add Integration**, search for **Water Heater Optimizer**.

### 配置流程 / Setup Steps

> **第 0 步 / Step 0**：先建一个进水温度的 **24h 移动平均** filter 辅助实体（建法见下方「进水均值辅助实体」一节），配置表单里的平均温度传感器要指向它。  
> **Step 0**: first create a **24h moving-average** `filter` helper for the inlet temperature (see the "Inlet Average Helper" section below) — the average sensor field must point at it.

| # | 字段 / Field | 说明 / Description |
|---|-------------|-------------------|
| 1 | **目标热水器 / Target Water Heater** | 选择你的 `water_heater` 实体。  
Select your `water_heater` entity. |
| 2 | **24h 平均进水温度传感器 / 24h Average Inlet Temperature Sensor** | 指向第 0 步建好的 filter 均值实体（选择器只列温度类传感器）。  
Point at the filter helper created in Step 0 (temperature sensors only). |
| 3 | **目标淋浴温度 / Target Shower Temperature** | 恒温花洒的设定温度（默认 37°C）。  
Your thermostatic mixer setpoint (default 37°C). |
| 4 | **热水比例 / Hot Water Ratio** | 期望从热水器提供的水量比例（默认 0.70 = 70%）。  
Desired proportion of water from the heater (default 0.70 = 70%). |
| 5 | **推荐设定温度下限/上限 / Recommended Setpoint Minimum/Maximum** | 推荐热水器设定温度的允许窗口（默认 40°C ~ 50°C），与目标淋浴温度无关。  
Allowed window for the recommended heater setpoint (default 40°C ~ 50°C), independent of the shower target temperature. |

### 可增量配置 / Incremental Configuration

你可以添加多个优化器实例——每个热水器或每个淋浴区一个，互不影响。  
You can add multiple optimizer instances — one per water heater or per shower zone — each runs independently with its own average sensor and parameters.

---

## 工作原理 / How It Works

进水温度取 **24 小时移动平均值**（外部 filter 辅助实体产出，集成不内置统计）。  
The inlet temperature is a **24-hour moving average** from an external `filter` helper (no built-in statistics).

```
Recommended Temp = Avg Inlet Temp + (Target Temp - Avg Inlet Temp) / Hot Water Ratio
```

- 仅当平均温度的**整数值变化**时重算推荐值；  
Recalculates only when the average's **integer value** changes;
- 自动调节开启时，重算结果与热水器**当前设定比对**，不同才下发 `water_heater.set_temperature`，相同不动；  
With auto-adjust on, the result is **compared against the heater's current setpoint** and only sent when different;
- 结果夹在你设定的下限/上限之间，并按热水器自身 min/max 限值再次夹紧。  
The result is clamped to your configured window and the heater's own min/max limits.

---

## 生成实体 / Created Entities

| 实体 / Entity | 类型 / Type | 说明 / Description |
|------------|-----------|-----------------|
| `sensor.{name}_recommended_temperature` | Sensor | 计算出的热水器推荐出口温度；属性 `inlet_temp_sensor` = 均值源实体、`applied_temp` = 最近一次实际下发值。  
Calculated optimal heater outlet temperature; attributes `inlet_temp_sensor` (average source) and `applied_temp` (last applied value). |
| `switch.{name}_auto_adjust` | Switch | 是否自动将推荐温度下发到热水器。  
Toggle automatic application of the recommended temperature. |
| `number.{name}_target_temperature` | Number | 淋浴目标温度，可直接修改并立即生效（30~60°C，写入条目配置，重启保留）。  
Shower target temperature, directly adjustable with immediate effect (30~60°C, persisted in the entry, survives restarts). |
| `number.{name}_hot_water_ratio` | Number | 热水比例，可直接修改并立即生效（0.30~0.95，写入条目配置，重启保留）。  
Hot water ratio, directly adjustable with immediate effect (0.30~0.95, persisted in the entry, survives restarts). |
| `number.{name}_recommended_minimum` | Number | 推荐设定温度下限，可直接修改并立即生效（30~60°C，写入条目配置，重启保留）。  
Recommended setpoint minimum, directly adjustable with immediate effect (30~60°C, persisted in the entry, survives restarts). |
| `number.{name}_recommended_maximum` | Number | 推荐设定温度上限，可直接修改并立即生效（30~70°C，写入条目配置，重启保留）。  
Recommended setpoint maximum, directly adjustable with immediate effect (30~70°C, persisted in the entry, survives restarts). |

---

## 进水均值辅助实体 / Inlet Average Helper

集成不内置统计——需要先建一个进水温度的 24h 移动平均实体，两种等价写法任选。  
The integration has no built-in statistics — create a 24h moving-average entity first; two equivalent ways.

**UI**：设置 → 设备与服务 → 辅助 → 创建辅助条目 → 过滤器：源实体选进水温度传感器，过滤器选「时间简单移动平均」，窗口 `24:00:00`，精度 `0`。  
**UI**: Settings → Devices & Services → Helpers → Create helper → Filter: source = inlet sensor, filter = Time simple moving average, window `24:00:00`, precision `0`.

**YAML**（`configuration.yaml`，改完可在开发者工具热加载传感器实体）：  
**YAML** (in `configuration.yaml`; sensor entities can be YAML-reloaded afterwards):

```yaml
sensor:
  - platform: filter
    name: "进水温度 24h 均值"
    entity_id: sensor.inlet_temperature
    filters:
      - filter: time_simple_moving_average
        window_size: "24:00"
        precision: 0
```

> filter 窗口为内存态：HA 重启后重新积累，头 24h 均值只基于部分数据；集成侧对引用值另有整数化兜底。  
> The filter window is in-memory: it re-accumulates after a HA restart (first-24h average is partial); the integration additionally rounds the value itself.

---

## 故障排除 / Troubleshooting

**Q: 推荐值一直是 unknown / 重启后没值？**  
**A:** 检查 filter 均值实体是否有状态：unavailable/unknown 时集成会忽略本次变化（INFO 日志可见）；均值实体有值时，集成启动/重载即读一次并算出推荐值。  
**A:** Check that the filter helper has a state: unavailable/unknown averages are ignored (INFO log line); once the average has a value, the integration reads it once on startup/reload and computes the recommendation.

**Q: 改了目标温度/比例，推荐值没变？**  
**A:** 参数热应用立即按最近一次有效均值重算；若从未有过有效均值，会记 INFO 并等均值就绪后生效。  
**A:** Parameters hot-apply and recalculate from the last valid average immediately; if no valid average has been seen yet, an INFO line notes it and the value appears once the average is ready.

**Q: 推荐温度看起来太低/太高。**  
**A:** 调整**热水比例**。比例越低，推荐温度越高（越保守）；比例越高，推荐温度越低（越激进）。  
Adjust the **Hot Water Ratio**. Lower ratio = higher recommended temperature (more conservative). Higher ratio = lower recommended temperature (more aggressive).

**Q: 自动调节已开启，但热水器温度没有变化。**  
**A:** 推荐值与热水器当前设定相同（整数比对口径）时不会重复下发，属正常；若确实不同，确保热水器实体支持 `water_heater.set_temperature`（部分云集成热水器需切换到手动/恒温等特定模式），跳过原因均记 INFO 日志。  
Identical (integer-compared) setpoints are not re-sent — that is normal; if they truly differ, make sure the entity supports `water_heater.set_temperature` (some cloud heaters need a specific mode), and check the INFO logs for skip reasons.

**Q: 我想用同一个进水传感器控制两台热水器。**  
**Q: Can I use the same inlet sensor for two heaters?**  
**A:** 可以。添加两个优化器实例，都指向同一个进水传感器，但各自选择不同的热水器。  
Yes. Add two optimizer instances, both pointing to the same inlet sensor but different water heaters.

---

## 更新日志 / Changelog

### 0.5.0
- 新增：推荐设定温度下限/上限原生化为 `number` 实体（30~60°C / 30~70°C，步进 1，BOX 输入），可在 HA 设备页直接调整，立即生效且重启保留；四个参数全部脱离文羽面板页即可调  
  Added: the recommended setpoint minimum/maximum are now native `number` entities (30~60°C / 30~70°C, step 1, BOX input), adjustable on the HA device page with immediate effect and persisted; all four parameters are tunable without the FumihaHub panel page
- 变更：调整下限/上限不再触发条目重载——与目标温度/热水比例同走热应用路径，推荐值按最近一次有效均值立即重算  
  Changed: changing the window bounds no longer reloads the entry — hot-applied like target temperature/hot water ratio, with the recommendation recalculated from the latest valid average immediately
- 移除：文羽面板页已下线（FumihaHub 壳信息页随删，参数与读数改在 HA 原生设备页查看/调整），manifest 不再依赖 `http`；升级后可删除旧目录残留的 `web.py` 与 `static/` 子目录  
  Removed: the FumihaHub shell info page is retired (parameters and readouts live on the native HA device page); the manifest no longer depends on `http` — after upgrading you may delete the leftover `web.py` and `static/` folder

### 0.4.0
- 重构：水温数据源改为进水温度的 **24h 移动平均**（HA 原生 `filter` 辅助实体，集成只引用不内置统计）；升级后请在条目「配置」中把平均温度传感器指向新建的 filter 实体（交付文档见仓库 `debug/` 目录）  
  Reworked: the inlet source is now a **24h moving average** from a stock `filter` helper; after upgrading, point the average sensor at your new helper via the entry's Configure dialog (delivery docs under the repo's `debug/` folder)
- 移除：触发器体系（实体状态/持续时间/固定时间三种触发及六项配置）、`take_snapshot` 服务、Reference Tap Temperature 实体、迟滞与下发冷却；旧条目无需迁移，残留 trigger 配置键被忽略  
  Removed: the trigger system (entity/duration/fixed-time and its six options), the `take_snapshot` service, the Reference Tap Temperature entity, and hysteresis/cooldown; existing entries migrate as-is, leftover trigger keys are ignored
- 新语义：仅当平均值**整数值变化**时重算；重算后与热水器当前设定**比对下发**，相同不动  
  New semantics: recalculate only on **integer changes** of the average; **compare-then-apply** against the heater's current setpoint — identical values are left alone
- 健壮性：全部跳过路径（均值不可用、热水器缺席/设定不可读）INFO 级落因，杜绝静默停摆；热水器自身 min/max 限值夹紧保留  
  Robustness: every skip path (average unavailable, heater missing/unreadable setpoint) logs at INFO — no more silent stalls; device-side min/max clamping retained
- 新增：FumihaHub 壳只读信息页（推荐温度/参数/总闸状态；需 FumihaHub 在场，无壳不报错仅记日志）  
  Added: read-only FumihaHub panel page (recommendation, parameters, auto-adjust state; requires FumihaHub, logs and does nothing without it)

### 0.3.0
> 已知待办（经审查评估延后）：forced 下发的服务调用在飞期间若进水传感器恰好上报，可能多发一条同值的 `set_temperature`（毫秒级窗口，存量类，概率 ~10⁻⁴~10⁻³/次改参，无振荡无风暴；2026-10-02 第三轮审查确认）  
> Known deferred: a millisecond window during an in-flight apply can send one redundant same-value `set_temperature` (pre-existing, reviewed and accepted)
- 新增：目标温度与热水比例以 `number` 实体暴露，可直接在仪表盘/更多信息对话框修改，立即生效  
  Added: target temperature and hot water ratio are now exposed as `number` entities, directly adjustable with immediate effect
- 改这两个参数不再触发条目重载（此前每次修改都会重建实体与触发器）；仅这两个键变化时走热应用路径，触发器等结构性配置变化仍照常重载  
  Changing these two no longer reloads the config entry (previously every change rebuilt entities and triggers); only these keys hot-apply, structural config changes still reload
- 修改参数后用最近一次快照的进水温度重算推荐值；自动调节开启时经 1.5 秒去抖合并后立即下发（绕过下发冷却，保留迟滞与设备限值夹紧）  
  After a change the recommendation is recalculated from the last snapshot; with auto-adjust on it applies after a 1.5 s debounce (bypassing the cooldown, hysteresis and device clamping still in effect)
- 数值写入条目配置（`entry.options`），HA 重启后保留；范围与配置流程一致（30~60°C / 0.30~0.95），拖动值按步长对齐  
  Values are written to the entry options and survive restarts; ranges match the config flow (30~60°C / 0.30~0.95), inputs snap to the step
- 修复（存量）：时长触发与启动补拍的回调此前被 HA 判为线程池任务执行，HA 2026.1 起跨线程检查会让时长触发整体失效、启动补拍报错；现已改为事件循环回调（`@callback`）  
  Fixed (pre-existing): duration-trigger and startup-snapshot callbacks were dispatched to the executor thread and broke under HA 2026.1's thread checks; they are now proper event-loop callbacks
- 修复：条目改名后实体/设备名照常刷新（标题/数据变化仍走重载，仅这两个可调参数走热应用）  
  Fixed: entity/device names refresh after renaming the entry (title/data changes still reload; only the two tunable parameters hot-apply)

### 0.2.1
- 修复：实体状态触发在 HA 启动完成（或条目重载）后补拍一次快照——此前要等进水温度传感器下次状态变化才有数据，夜间进水温度几乎不变，推荐/参考温度传感器会长期 unknown。启动补拍经 `async_at_started` 延后到各集成状态就绪，并尊重 from/to_state 过滤口径  
  Fixed: the entity-state trigger now takes a snapshot once HA has started (or the entry reloaded) — previously sensors stayed unknown until the inlet sensor's next state change
- 修复：热水器实体状态缺席时不再盲发原始推荐值（无法夹紧设备限值、无法迟滞比较），记日志跳过等下次快照  
  Fixed: skip applying (with a log) when the heater entity state is missing instead of blindly sending the raw recommendation
- 修复：进水温度为非有限值（nan/inf）时跳过快照，不再炸掉启动流程  
  Fixed: non-finite inlet temperatures (nan/inf) now skip the snapshot instead of crashing startup
- 新增：`take_snapshot` 服务与 `entry_id` 字段的中英文翻译（services 段）；推荐值被窗口夹紧时输出 debug 日志  
  Added: zh/en translations for the take_snapshot service; debug log when the recommendation is clamped
- 清理：import 排序（ruff 清零）  
  Chores: import sorting (ruff cleared)

### 0.2.0
- 修复配置误报：淋浴目标温度不再被要求落在推荐设定温度窗口（最低/最高）内，两者本就是独立参数
  Fixed config false positive: the shower target temperature is no longer required to fall inside the recommended setpoint window — they are independent parameters
- 删除 `target_out_of_range` 校验；「最低温度必须低于最高温度」报错现在会回显实际填写的数值
  Removed the `target_out_of_range` validation; the invalid-range error now shows the entered values
- 字段「最低温度/最高温度」更名为「推荐设定温度下限/上限」以消除歧义
  Renamed "Minimum/Maximum Temperature" fields to "Recommended Setpoint Minimum/Maximum" for clarity
- 修复下发温度时对热水器自身限值的取整方向（下限向上取整、上限向下取整），避免 41.5°C 这类限值被舍入到限值之外导致下发被拒
  Fixed rounding direction of the heater's own limits when applying temperature (ceil for the lower bound, floor for the upper), preventing limits like 41.5°C from being rounded outside the allowed range and getting rejected

### 0.0.8
- 9 月审计修复主体：服务注册带 schema、下发防护（迟滞/冷却/设备限值夹紧）、Platform 枚举、`setdefault` 防御等  
  Main batch of the September audit fixes: service schema, apply guards (hysteresis/cooldown/device clamp), Platform enum, defensive `setdefault`

### 0.0.7
- 无代码变更（发布维护）  
  No code changes (release maintenance)

### 0.0.6
- 翻译与 manifest 小修  
  Minor translation and manifest touch-ups

### 0.0.5
- 修复 manifest 中的仓库链接与用户名拼写  
  Fixed repository URL and username typo in manifest
- 支持通过"配置"按钮二次编辑已添加的集成条目（Options Flow）  
  Existing entries can now be re-configured via the Configure button (options flow)
- 自动调节开关状态在 HA 重启后自动恢复  
  Auto-adjust switch state is now restored across restarts

### 初始版本（V0.0.1~V0.0.4）
- 初始版本 / Initial release
- 支持实体状态、持续时间、固定时间三种触发方式  
  Support for entity state, duration, and fixed-time triggers
- 自动调节开关  
  Auto-adjust switch
- 手动快照服务  
  Manual snapshot service
- 多实例增量配置  
  Multi-instance (incremental) configuration
