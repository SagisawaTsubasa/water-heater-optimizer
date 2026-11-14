"""Constants for Water Heater Optimizer."""

DOMAIN = "water_heater_optimizer"

CONF_WATER_HEATER = "water_heater"
CONF_INLET_TEMP_SENSOR = "inlet_temp_sensor"
CONF_TARGET_TEMP = "target_temp"
CONF_HOT_WATER_RATIO = "hot_water_ratio"
CONF_MIN_TEMP = "min_temp"
CONF_MAX_TEMP = "max_temp"

DEFAULT_TARGET_TEMP = 37
DEFAULT_RATIO = 0.70
DEFAULT_MIN_TEMP = 40
DEFAULT_MAX_TEMP = 50

SIGNAL_UPDATE = f"{DOMAIN}_update"

# FumihaHub 页面接入契约（fumiha_hub/registry.py 模块文档）：两个字符串常量
# + 一个 dict，按契约在本仓复制字面量，绝不 import 壳包。探针 = 键存在 ⇔
# 壳条目已加载且未删除；绝不能自己 setdefault 创建该 dict（无壳环境下页面
# 会因此永久不可达）。
HUB_REGISTRY_KEY = "fumiha_hub_registry"
HUB_BUS_EVENT_PAGE_CHANGED = "fumiha_hub_page_changed"
HUB_PAGE_ID = "water_heater_optimizer.main"
HUB_PAGE_TITLE = "热水器温度优化器"
HUB_PAGE_ORDER = 60
