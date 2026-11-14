"""Config flow for Water Heater Optimizer."""

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.helpers.selector import (
    EntitySelector,
    EntitySelectorConfig,
    NumberSelector,
    NumberSelectorConfig,
)

from .const import (
    CONF_HOT_WATER_RATIO,
    CONF_INLET_TEMP_SENSOR,
    CONF_MAX_TEMP,
    CONF_MIN_TEMP,
    CONF_TARGET_TEMP,
    CONF_WATER_HEATER,
    DEFAULT_MAX_TEMP,
    DEFAULT_MIN_TEMP,
    DEFAULT_RATIO,
    DEFAULT_TARGET_TEMP,
    DOMAIN,
)


def _fmt_temp(value) -> str:
    """Format a temperature for display in error messages."""
    if value is None:
        return "-"
    try:
        num = float(value)
    except (TypeError, ValueError):
        return str(value)
    return str(int(num)) if num.is_integer() else str(num)


def _effective_water_heater(entry) -> str | None:
    """条目当前实际控制的热水器：options 优先，data 兜底（R1 P2#4）。"""
    return entry.options.get(
        CONF_WATER_HEATER, entry.data.get(CONF_WATER_HEATER)
    )


def _validate_ranges(user_input: dict) -> tuple[str | None, str, str]:
    """Validate min/max temperature window (M1). Returns (error key, min, max).

    淋浴目标温度与热水器设定窗口是两个量纲，不做跨项约束；
    这里只校验窗口本身 min < max。
    """
    min_temp = user_input.get(CONF_MIN_TEMP, DEFAULT_MIN_TEMP)
    max_temp = user_input.get(CONF_MAX_TEMP, DEFAULT_MAX_TEMP)
    min_disp, max_disp = _fmt_temp(min_temp), _fmt_temp(max_temp)
    try:
        min_val, max_val = float(min_temp), float(max_temp)
    except (TypeError, ValueError):
        return "invalid_range", min_disp, max_disp
    if min_val >= max_val:
        return "invalid_range", min_disp, max_disp
    return None, min_disp, max_disp


class WaterHeaterOptimizerConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow."""

    VERSION = 1

    @staticmethod
    def async_get_options_flow(config_entry):
        """Return the options flow for an existing entry."""
        return WaterHeaterOptimizerOptionsFlow()

    async def async_step_user(self, user_input=None):
        """Single-form setup: two entities plus four parameters."""
        errors = {}
        placeholders = {}

        if user_input is not None:
            error, min_disp, max_disp = _validate_ranges(user_input)
            if error is not None:
                errors["base"] = error
                placeholders = {"min_temp": min_disp, "max_temp": max_disp}
            else:
                # 用热水器实体做唯一标识，第一步就查重 (L5)
                await self.async_set_unique_id(user_input[CONF_WATER_HEATER])
                self._abort_if_unique_id_configured()
                # 兼容旧版按标题生成的 unique_id：同热水器的旧条目也要查重。
                # R1 P2#4：读"有效热水器"（options 优先，data 兜底）——options
                # flow 允许改热水器，只看 data 会误报已配置
                for existing in self._async_current_entries():
                    if _effective_water_heater(existing) == user_input[CONF_WATER_HEATER]:
                        return self.async_abort(reason="already_configured")
                title = f"Optimizer {user_input[CONF_WATER_HEATER]}"
                return self.async_create_entry(title=title, data=user_input)

        data_schema = vol.Schema({
            vol.Required(CONF_WATER_HEATER): EntitySelector(
                EntitySelectorConfig(domain="water_heater")
            ),
            vol.Required(CONF_INLET_TEMP_SENSOR): EntitySelector(
                # R1 P3#11：限定温度类传感器，拦住误选非温度实体静默算错
                EntitySelectorConfig(domain="sensor", device_class="temperature")
            ),
            vol.Required(CONF_TARGET_TEMP, default=DEFAULT_TARGET_TEMP): NumberSelector(
                NumberSelectorConfig(min=30, max=60, step=1, unit_of_measurement="°C")
            ),
            vol.Required(CONF_HOT_WATER_RATIO, default=DEFAULT_RATIO): NumberSelector(
                NumberSelectorConfig(min=0.3, max=0.95, step=0.05, mode="slider")
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
            description_placeholders=placeholders,
        )


class WaterHeaterOptimizerOptionsFlow(config_entries.OptionsFlow):
    """Handle re-configuration of an existing entry via the options flow."""

    def _current(self, key, default=None):
        """Read current value: options take priority over initial data."""
        return self.config_entry.options.get(
            key, self.config_entry.data.get(key, default)
        )

    async def async_step_init(self, user_input=None):
        """Single-form re-configuration, prefilled with current values."""
        errors = {}
        placeholders = {}

        if user_input is not None:
            error, min_disp, max_disp = _validate_ranges(user_input)
            if error is not None:
                errors["base"] = error
                placeholders = {"min_temp": min_disp, "max_temp": max_disp}
            else:
                # R1 P2#4：改热水器时按其他条目的"有效热水器"查重（HA 对
                # unique_id 冲突只记 error 不拦截，必须自查），通过后把
                # unique_id/title 一并原子更新——否则同设备可双控、旧设备
                # 误报已配置。options/unique_id/title 一次 update_entry 写入，
                # 只触发一次 update listener；随后的 create_entry 落 options
                # 时已相等，HA 不再重复触发
                new_heater = user_input[CONF_WATER_HEATER]
                for existing in self.hass.config_entries.async_entries(DOMAIN):
                    if (
                        existing is not self.config_entry
                        and _effective_water_heater(existing) == new_heater
                    ):
                        errors["base"] = "already_configured"
                        break
                else:
                    self.hass.config_entries.async_update_entry(
                        self.config_entry,
                        options=user_input,
                        unique_id=new_heater,
                        title=f"Optimizer {new_heater}",
                    )
                    return self.async_create_entry(title="", data=user_input)

        data_schema = vol.Schema({
            vol.Required(
                CONF_WATER_HEATER, default=self._current(CONF_WATER_HEATER)
            ): EntitySelector(
                EntitySelectorConfig(domain="water_heater")
            ),
            vol.Required(
                CONF_INLET_TEMP_SENSOR, default=self._current(CONF_INLET_TEMP_SENSOR)
            ): EntitySelector(
                # R1 P3#11：与初始流一致，限定温度类传感器
                EntitySelectorConfig(domain="sensor", device_class="temperature")
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
            description_placeholders=placeholders,
        )
