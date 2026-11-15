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
