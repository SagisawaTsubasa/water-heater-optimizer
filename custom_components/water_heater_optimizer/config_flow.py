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
            # Store step 1 data and proceed to step 2
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
            await self.async_set_unique_id(title)
            self._abort_if_unique_id_configured()
            return self.async_create_entry(title=title, data=self._data)

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
            return self.async_create_entry(title="", data=self._data)

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
