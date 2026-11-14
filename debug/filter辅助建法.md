# 24h 平均进水温度 filter 辅助实体建法

v0.4.0 集成只引用一个**已存在的** 24h 平均温度实体，不内置统计。该实体由 HA 原生 `filter` 辅助产出，需先自建。以下两种建法等价，任选其一。

## 前置

- 一个上报进水（自来水）温度的温度类传感器实体，下文以 `sensor.inlet_temperature` 为例。
- filter 为**源状态驱动**：源传感器不更新，均值窗口不滚动。进水温度日上报频次足够（计划书风险登记，用户知情）。

## 方法一：UI（推荐）

路径：**设置 → 设备与服务 → 辅助 → 创建辅助条目 → 过滤器（Filter）**

1. 名称：如「进水温度 24h 均值」。
2. 源实体：选择进水温度传感器。
3. 过滤器：添加 → **时间简单移动平均（Time simple moving average）**
   - 窗口大小（Window size）：`24:00:00`（24 小时）
   - 精度（Precision）：`0`（输出整数）
4. 保存后得到新实体（如 `sensor.jin_shui_wen_du_24h_jun_zhi`），把它填进集成条目的「24h 平均进水温度传感器」字段（见《条目重配指引.md》）。

## 方法二：YAML

`configuration.yaml`：

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

改完保存后：开发者工具 → YAML → 重新加载「所有传感器实体」（filter 属 sensor 平台，可热加载，无需重启 HA）。

## 行为要点

- **冷启动**：filter 窗口是内存态，HA 重启后重新积累——头 24h 的均值只基于已收到的部分数据（计划书 §1 风险登记，用户知情，可接受）。
- **整数化双保险**：`precision: 0` 让 filter 直接输出整数；集成侧对引用值另有 `round()` 兜底，precision 不为 0 也能工作，但整数输出展示更干净。
- **精度与重算频率**：集成只在平均值的**整数值变化**时重算推荐值（整数步进天然防抖），所以日均温平缓漂移不会造成频繁下发。

## 验证

实体建好后点开状态：数值应为整数，随源传感器每次上报缓慢变化（24h 窗口内加权平均，单次上报影响很小）。
