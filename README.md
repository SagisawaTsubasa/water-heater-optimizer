# Water Heater Optimizer

> 根据自来水温度动态计算燃气热水器最佳出口温度，让恒温淋浴全年稳定。  
> Dynamically calculates the optimal gas water heater outlet temperature based on tap water temperature for stable thermostatic showers year-round.

**Home Assistant version:** 26.1.3  
**Programmer:** Kimi (Moonshot AI)  
**License:** MIT

---

## 安装 / Installation

### HACS (推荐 / Recommended)
1. 在 HACS 中添加此仓库为自定义仓库。  
   Add this repository as a custom repository in HACS.
2. 安装 **Water Heater Optimizer**。  
   Install **Water Heater Optimizer**.
3. 重启 Home Assistant。  
   Restart Home Assistant.

### 手动 / Manual
1. 将 `custom_components/water_heater_optimizer` 复制到 Home Assistant 的 `custom_components` 目录。  
   Copy the `custom_components/water_heater_optimizer` folder into your Home Assistant `custom_components` directory.
2. 重启 Home Assistant。  
   Restart Home Assistant.

---

## 配置 / Configuration

前往 **设置 → 设备与服务 → 添加集成**，搜索 **Water Heater Optimizer**。  
Go to **Settings → Devices & Services → Add Integration**, search for **Water Heater Optimizer**.

### 配置流程 / Setup Steps

| # | 字段 / Field | 说明 / Description |
|---|-------------|-------------------|
| 1 | **目标热水器 / Target Water Heater** | 选择你的 `water_heater` 实体。  
Select your `water_heater` entity. |
| 2 | **进水温度传感器 / Inlet Temperature Sensor** | 选择报告自来水温度的传感器。  
Select the sensor reporting inlet (tap) water temperature. |
| 3 | **快照触发条件 / Snapshot Trigger** | 选择如何捕获进水温度：实体状态变化、持续时间、或固定时间。  
Choose how to capture the inlet temperature: entity state change, duration, or fixed time. |
| 4 | **目标淋浴温度 / Target Shower Temperature** | 恒温花洒的设定温度（默认 37°C）。  
Your thermostatic mixer setpoint (default 37°C). |
| 5 | **热水比例 / Hot Water Ratio** | 期望从热水器提供的水量比例（默认 0.70 = 70%）。  
Desired proportion of water from the heater (default 0.70 = 70%). |
| 6 | **推荐设定温度下限/上限 / Recommended Setpoint Minimum/Maximum** | 推荐热水器设定温度的允许窗口（默认 40°C ~ 50°C），与目标淋浴温度无关。  
Allowed window for the recommended heater setpoint (default 40°C ~ 50°C), independent of the shower target temperature. |

### 可增量配置 / Incremental Configuration

你可以添加多个优化器实例——每个热水器或每个淋浴区一个，互不影响。  
You can add multiple optimizer instances — one per water heater or per shower zone — each runs independently with its own sensors, triggers, and parameters.

---

## 工作原理 / How It Works

```
Recommended Temp = Tap Temp + (Target Temp - Tap Temp) / Hot Water Ratio
```

结果会被限制在你设定的最低/最高温度之间。  
The result is clamped between your configured min/max values.

---

## 生成实体 / Created Entities

| 实体 / Entity | 类型 / Type | 说明 / Description |
|------------|-----------|-----------------|
| `sensor.{name}_recommended_temperature` | Sensor | 计算出的热水器推荐出口温度。  
Calculated optimal heater outlet temperature. |
| `sensor.{name}_reference_tap_temperature` | Sensor | 上次快照的自来水温度。  
Last captured inlet water temperature. |
| `switch.{name}_auto_adjust` | Switch | 是否自动将推荐温度下发到热水器。  
Toggle automatic application of the recommended temperature. |
| `number.{name}_target_temperature` | Number | 淋浴目标温度，可直接修改并立即生效（30~60°C，写入条目配置，重启保留）。  
Shower target temperature, directly adjustable with immediate effect (30~60°C, persisted in the entry, survives restarts). |
| `number.{name}_hot_water_ratio` | Number | 热水比例，可直接修改并立即生效（0.30~0.95，写入条目配置，重启保留）。  
Hot water ratio, directly adjustable with immediate effect (0.30~0.95, persisted in the entry, survives restarts). |

---

## 服务 / Services

### `water_heater_optimizer.take_snapshot`

手动触发指定实例的快照。  
Manually trigger a snapshot for a specific instance.

```yaml
service: water_heater_optimizer.take_snapshot
data:
  entry_id: "YOUR_CONFIG_ENTRY_ID"
```

---

## 典型触发配置 / Typical Trigger Configurations

### 传感器挂起/激活型（淋浴开始）
- **触发类型 / Trigger Type:** Entity State Change
- **触发实体 / Entity:** 进水温度传感器
- **从状态 / From:** `unavailable`
- **到状态 / To:** *(留空 / leave empty)*

### 用水持续 N 秒后确认稳定
- **触发类型 / Trigger Type:** Duration
- **触发实体 / Entity:** 进水温度传感器
- **持续时间 / Duration:** `120` 秒

### 每日凌晨固定刷新
- **触发类型 / Trigger Type:** Fixed Time
- **时间 / Time:** `06:00`

---

## 故障排除 / Troubleshooting

**Q: 改了目标温度/比例，推荐值没变？**  
**A:** 推荐值基于"最近一次快照的进水温度"计算，修改参数会立即按该值重算；刚重启/重载条目后还没有任何快照时，参数已生效但推荐值要等下一次快照（或手动调用 `take_snapshot`）才刷新。  
**A:** The recommendation is based on the last snapshot's inlet temperature and recalculates immediately on change; right after a restart/reload (no snapshot yet), the change takes effect but the displayed value refreshes on the next snapshot (or a manual `take_snapshot`).

**Q: 推荐温度看起来太低/太高。**  
**A:** 调整**热水比例**。比例越低，推荐温度越高（越保守）；比例越高，推荐温度越低（越激进）。  
Adjust the **Hot Water Ratio**. Lower ratio = higher recommended temperature (more conservative). Higher ratio = lower recommended temperature (more aggressive).

**Q: 自动调节已开启，但热水器温度没有变化。**  
**A:** 确保你的热水器实体支持 `water_heater.set_temperature`。部分云集成热水器需要切换到特定模式（如手动/恒温）才能接受外部温度指令。  
Ensure your water heater entity supports `water_heater.set_temperature`. Some cloud-integrated heaters require a specific mode (e.g., manual/thermostat) to accept external commands.

**Q: 我想用同一个进水传感器控制两台热水器。**  
**Q: Can I use the same inlet sensor for two heaters?**  
**A:** 可以。添加两个优化器实例，都指向同一个进水传感器，但各自选择不同的热水器。  
Yes. Add two optimizer instances, both pointing to the same inlet sensor but different water heaters.

---

## 更新日志 / Changelog

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
