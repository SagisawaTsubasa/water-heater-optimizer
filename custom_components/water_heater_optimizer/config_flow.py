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

    async def async_step_user(self, user_input=None):
        """Handle the initial step."""
        errors = {}

        if user_input is not None:
            title = f"Optimizer {user_input[CONF_WATER_HEATER]}"
            await self.async_set_unique_id(title)
            self._abort_if_unique_id_configured()
            return self.async_create_entry(title=title, data=user_input)

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
                    {"label": "Entity State Change", "value": TRIGGER_TYPE_ENTITY_STATE},
                    {"label": "Duration", "value": TRIGGER_TYPE_DURATION},
                    {"label": "Fixed Time", "value": TRIGGER_TYPE_FIXED_TIME},
                ])
            ),
            vol.Optional(CONF_TRIGGER_ENTITY): EntitySelector(),
            vol.Optional(CONF_TRIGGER_FROM_STATE): TextSelector(),
            vol.Optional(CONF_TRIGGER_TO_STATE): TextSelector(),
            vol.Optional(CONF_TRIGGER_DURATION, default=120): NumberSelector(
                NumberSelectorConfig(min=10, max=3600, step=10, unit_of_measurement="s")
            ),
            vol.Optional(CONF_TRIGGER_TIME, default="06:00"): TimeSelector(),
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
            description_placeholders={
                "docs": "https://github.com/your-github-username/water_heater_optimizer"
            },
        )
