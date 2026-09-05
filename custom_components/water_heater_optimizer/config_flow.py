"""Config flow for Water Heater Optimizer."""

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.helpers.selector import (
    EntitySelector,
    EntitySelectorConfig,
    NumberSelector,
    NumberSelectorConfig,
    SelectSelector,
    SelectSelectorConfig,
    TimeSelector,
    TextSelector,
)

from .const import (
    DOMAIN,
    CONF_WATER_HEATER,
    CONF_INLET_TEMP_SENSOR,
    CONF_TRIGGER_TYPE,
    CONF_TRIGGER_ENTITY,
    CONF_TRIGGER_FROM_STATE,
    CONF_TRIGGER_TO_STATE,
    CONF_TRIGGER_DURATION,
    CONF_TRIGGER_TIME,
    CONF_TARGET_TEMP,
    CONF_HOT_WATER_RATIO,
    CONF_MIN_TEMP,
    CONF_MAX_TEMP,
    DEFAULT_TARGET_TEMP,
    DEFAULT_RATIO,
    DEFAULT_MIN_TEMP,
    DEFAULT_MAX_TEMP,
    TRIGGER_TYPE_ENTITY_STATE,
    TRIGGER_TYPE_DURATION,
    TRIGGER_TYPE_FIXED_TIME,
)

# 每种触发类型实际使用的配置键：切换类型后清理其余键 (L6)
_TRIGGER_KEY_MAP = {
    TRIGGER_TYPE_ENTITY_STATE: (CONF_TRIGGER_ENTITY, CONF_TRIGGER_FROM_STATE, CONF_TRIGGER_TO_STATE),
    TRIGGER_TYPE_DURATION: (CONF_TRIGGER_ENTITY, CONF_TRIGGER_TO_STATE, CONF_TRIGGER_DURATION),
    TRIGGER_TYPE_FIXED_TIME: (CONF_TRIGGER_TIME,),
}
_ALL_TRIGGER_KEYS = tuple(
    dict.fromkeys(key for keys in _TRIGGER_KEY_MAP.values() for key in keys)
)


def _clean_trigger_keys(data: dict) -> dict:
    """Drop trigger-specific keys not belonging to the configured trigger type."""
    keep = _TRIGGER_KEY_MAP.get(data.get(CONF_TRIGGER_TYPE), ())
    for key in _ALL_TRIGGER_KEYS:
        if key not in keep:
            data.pop(key, None)
    return data


def _validate_ranges(user_input: dict) -> str | None:
    """Cross-validate min/max/target temperatures (M1). Returns error key or None."""
    min_temp = user_input.get(CONF_MIN_TEMP, DEFAULT_MIN_TEMP)
    max_temp = user_input.get(CONF_MAX_TEMP, DEFAULT_MAX_TEMP)
    target = user_input.get(CONF_TARGET_TEMP, DEFAULT_TARGET_TEMP)
    try:
        min_temp, max_temp, target = float(min_temp), float(max_temp), float(target)
    except (TypeError, ValueError):
        return "invalid_range"
    if min_temp >= max_temp:
        return "invalid_range"
    if not min_temp <= target <= max_temp:
        return "target_out_of_range"
    return None


class WaterHeaterOptimizerConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow."""

    VERSION = 1

    @staticmethod
    def async_get_options_flow(config_entry):
        """Return the options flow for an existing entry."""
        return WaterHeaterOptimizerOptionsFlow()

    async def async_step_user(self, user_input=None):
        """Step 1: Basic configuration."""
        errors = {}

        if user_input is not None:
            error = _validate_ranges(user_input)
            if error is not None:
                errors["base"] = error
            else:
                # 用热水器实体做唯一标识，第一步就查重 (L5)
                await self.async_set_unique_id(user_input[CONF_WATER_HEATER])
                self._abort_if_unique_id_configured()
                # 兼容旧版按标题生成的 unique_id：同热水器的旧条目也要查重
                for existing in self._async_current_entries():
                    if existing.data.get(CONF_WATER_HEATER) == user_input[CONF_WATER_HEATER]:
                        return self.async_abort(reason="already_configured")
                self._data = user_input
                return await self.async_step_trigger()

        data_schema = vol.Schema({
            vol.Required(CONF_WATER_HEATER): EntitySelector(
                EntitySelectorConfig(domain="water_heater")
            ),
            vol.Required(CONF_INLET_TEMP_SENSOR): EntitySelector(
                EntitySelectorConfig(domain="sensor")
            ),
            vol.Required(CONF_TARGET_TEMP, default=DEFAULT_TARGET_TEMP): NumberSelector(
                NumberSelectorConfig(min=30, max=60, step=1, unit_of_measurement="°C")
            ),
            vol.Required(CONF_HOT_WATER_RATIO, default=DEFAULT_RATIO): NumberSelector(
                NumberSelectorConfig(min=0.3, max=0.95, step=0.05, mode="slider")
            ),
            vol.Required(CONF_TRIGGER_TYPE, default=TRIGGER_TYPE_ENTITY_STATE): SelectSelector(
                SelectSelectorConfig(options=[
                    TRIGGER_TYPE_ENTITY_STATE,
                    TRIGGER_TYPE_DURATION,
                    TRIGGER_TYPE_FIXED_TIME,
                ])
            ),
            vol.Optional(CONF_MIN_TEMP, default=DEFAULT_MIN_TEMP): NumberSelector(
                NumberSelectorConfig(min=30, max=60, step=1, unit_of_measurement="°C")
            ),
            vol.Optional(CONF_MAX_TEMP, default=DEFAULT_MAX_TEMP): NumberSelector(
                NumberSelectorConfig(min=30, max=70, step=1, unit_of_measurement="°C")
            ),
        })

        return self.async_show_form(
            step_id="user",
            data_schema=data_schema,
            errors=errors,
        )

    async def async_step_trigger(self, user_input=None):
        """Step 2: Trigger configuration based on trigger type."""
        errors = {}
        trigger_type = self._data[CONF_TRIGGER_TYPE]

        if user_input is not None:
            # Merge step 1 and step 2 data
            self._data.update(user_input)
            title = f"Optimizer {self._data[CONF_WATER_HEATER]}"
            return self.async_create_entry(title=title, data=_clean_trigger_keys(self._data))

        # Build schema based on trigger type
        if trigger_type == TRIGGER_TYPE_ENTITY_STATE:
            data_schema = vol.Schema({
                vol.Optional(CONF_TRIGGER_ENTITY): EntitySelector(),
                vol.Optional(CONF_TRIGGER_FROM_STATE): TextSelector(),
                vol.Optional(CONF_TRIGGER_TO_STATE): TextSelector(),
            })
            description = "Configure entity state change trigger. Leave Trigger Entity empty to use the inlet temperature sensor."

        elif trigger_type == TRIGGER_TYPE_DURATION:
            data_schema = vol.Schema({
                vol.Optional(CONF_TRIGGER_ENTITY): EntitySelector(),
                vol.Optional(CONF_TRIGGER_TO_STATE): TextSelector(),
                vol.Optional(CONF_TRIGGER_DURATION, default=120): NumberSelector(
                    NumberSelectorConfig(min=10, max=3600, step=10, unit_of_measurement="s")
                ),
            })
            description = "Configure duration trigger. Snapshot will be taken after the entity has been in the specified state for the given duration."

        elif trigger_type == TRIGGER_TYPE_FIXED_TIME:
            data_schema = vol.Schema({
                vol.Optional(CONF_TRIGGER_TIME, default="06:00"): TimeSelector(),
            })
            description = "Configure fixed time trigger. Snapshot will be taken daily at the specified time."

        else:
            data_schema = vol.Schema({})
            description = "Unknown trigger type."

        return self.async_show_form(
            step_id="trigger",
            data_schema=data_schema,
            errors=errors,
            description_placeholders={"description": description},
        )


class WaterHeaterOptimizerOptionsFlow(config_entries.OptionsFlow):
    """Handle re-configuration of an existing entry via the options flow."""

    def _current(self, key, default=None):
        """Read current value: options take priority over initial data."""
        return self.config_entry.options.get(
            key, self.config_entry.data.get(key, default)
        )

    def _optional(self, key):
        """Build vol.Optional prefilled only when a value already exists."""
        value = self._current(key)
        if value is not None:
            return vol.Optional(key, default=value)
        return vol.Optional(key)

    async def async_step_init(self, user_input=None):
        """Step 1: Basic configuration, prefilled with current values."""
        errors = {}

        if user_input is not None:
            error = _validate_ranges(user_input)
            if error is not None:
                errors["base"] = error
            else:
                self._data = user_input
                return await self.async_step_trigger()

        data_schema = vol.Schema({
            vol.Required(
                CONF_WATER_HEATER, default=self._current(CONF_WATER_HEATER)
            ): EntitySelector(
                EntitySelectorConfig(domain="water_heater")
            ),
            vol.Required(
                CONF_INLET_TEMP_SENSOR, default=self._current(CONF_INLET_TEMP_SENSOR)
            ): EntitySelector(
                EntitySelectorConfig(domain="sensor")
            ),
            vol.Required(
                CONF_TARGET_TEMP,
                default=self._current(CONF_TARGET_TEMP, DEFAULT_TARGET_TEMP),
            ): NumberSelector(
                NumberSelectorConfig(min=30, max=60, step=1, unit_of_measurement="°C")
            ),
            vol.Required(
                CONF_HOT_WATER_RATIO,
                default=self._current(CONF_HOT_WATER_RATIO, DEFAULT_RATIO),
            ): NumberSelector(
                NumberSelectorConfig(min=0.3, max=0.95, step=0.05, mode="slider")
            ),
            vol.Required(
                CONF_TRIGGER_TYPE,
                default=self._current(CONF_TRIGGER_TYPE, TRIGGER_TYPE_ENTITY_STATE),
            ): SelectSelector(
                SelectSelectorConfig(options=[
                    TRIGGER_TYPE_ENTITY_STATE,
                    TRIGGER_TYPE_DURATION,
                    TRIGGER_TYPE_FIXED_TIME,
                ])
            ),
            vol.Optional(
                CONF_MIN_TEMP,
                default=self._current(CONF_MIN_TEMP, DEFAULT_MIN_TEMP),
            ): NumberSelector(
                NumberSelectorConfig(min=30, max=60, step=1, unit_of_measurement="°C")
            ),
            vol.Optional(
                CONF_MAX_TEMP,
                default=self._current(CONF_MAX_TEMP, DEFAULT_MAX_TEMP),
            ): NumberSelector(
                NumberSelectorConfig(min=30, max=70, step=1, unit_of_measurement="°C")
            ),
        })

        return self.async_show_form(
            step_id="init",
            data_schema=data_schema,
            errors=errors,
        )

    async def async_step_trigger(self, user_input=None):
        """Step 2: Trigger configuration based on trigger type."""
        errors = {}
        trigger_type = self._data[CONF_TRIGGER_TYPE]

        if user_input is not None:
            self._data.update(user_input)
            return self.async_create_entry(title="", data=_clean_trigger_keys(self._data))

        if trigger_type == TRIGGER_TYPE_ENTITY_STATE:
            data_schema = vol.Schema({
                self._optional(CONF_TRIGGER_ENTITY): EntitySelector(),
                self._optional(CONF_TRIGGER_FROM_STATE): TextSelector(),
                self._optional(CONF_TRIGGER_TO_STATE): TextSelector(),
            })
            description = "Configure entity state change trigger. Leave Trigger Entity empty to use the inlet temperature sensor."

        elif trigger_type == TRIGGER_TYPE_DURATION:
            data_schema = vol.Schema({
                self._optional(CONF_TRIGGER_ENTITY): EntitySelector(),
                self._optional(CONF_TRIGGER_TO_STATE): TextSelector(),
                vol.Optional(
                    CONF_TRIGGER_DURATION,
                    default=self._current(CONF_TRIGGER_DURATION, 120),
                ): NumberSelector(
                    NumberSelectorConfig(min=10, max=3600, step=10, unit_of_measurement="s")
                ),
            })
            description = "Configure duration trigger. Snapshot will be taken after the entity has been in the specified state for the given duration."

        elif trigger_type == TRIGGER_TYPE_FIXED_TIME:
            data_schema = vol.Schema({
                vol.Optional(
                    CONF_TRIGGER_TIME,
                    default=self._current(CONF_TRIGGER_TIME, "06:00"),
                ): TimeSelector(),
            })
            description = "Configure fixed time trigger. Snapshot will be taken daily at the specified time."

        else:
            data_schema = vol.Schema({})
            description = "Unknown trigger type."

        return self.async_show_form(
            step_id="trigger",
            data_schema=data_schema,
            errors=errors,
            description_placeholders={"description": description},
        )
