"""Constants for Water Heater Optimizer."""

DOMAIN = "water_heater_optimizer"

CONF_WATER_HEATER = "water_heater"
CONF_INLET_TEMP_SENSOR = "inlet_temp_sensor"
CONF_TRIGGER_TYPE = "trigger_type"
CONF_TRIGGER_ENTITY = "trigger_entity"
CONF_TRIGGER_FROM_STATE = "trigger_from_state"
CONF_TRIGGER_TO_STATE = "trigger_to_state"
CONF_TRIGGER_DURATION = "trigger_duration"
CONF_TRIGGER_TIME = "trigger_time"
CONF_TARGET_TEMP = "target_temp"
CONF_HOT_WATER_RATIO = "hot_water_ratio"
CONF_MIN_TEMP = "min_temp"
CONF_MAX_TEMP = "max_temp"

DEFAULT_TARGET_TEMP = 37
DEFAULT_RATIO = 0.70
DEFAULT_MIN_TEMP = 40
DEFAULT_MAX_TEMP = 50

TRIGGER_TYPE_ENTITY_STATE = "entity_state"
TRIGGER_TYPE_DURATION = "duration"
TRIGGER_TYPE_FIXED_TIME = "fixed_time"

ATTR_RECOMMENDED_TEMP = "recommended_temp"
ATTR_REFERENCE_TAP_TEMP = "reference_tap_temp"
ATTR_AUTO_ADJUST = "auto_adjust"

SIGNAL_UPDATE = f"{DOMAIN}_update"
