"""Water Heater Optimizer integration."""

import logging

import voluptuous as vol
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.typing import ConfigType

from .const import DOMAIN, SERVICE_TAKE_SNAPSHOT
from .optimizer import WaterHeaterOptimizer

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[Platform] = [Platform.SENSOR, Platform.SWITCH]

TAKE_SNAPSHOT_SCHEMA = vol.Schema({vol.Required("entry_id"): cv.string})


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Set up the integration."""
    hass.data.setdefault(DOMAIN, {})
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up a config entry."""
    optimizer = WaterHeaterOptimizer(hass, entry)
    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = optimizer
    await optimizer.async_setup()

    # Reload the entry automatically when options are changed
    entry.async_on_unload(entry.add_update_listener(_async_update_listener))

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    if not hass.services.has_service(DOMAIN, SERVICE_TAKE_SNAPSHOT):

        async def _handle_snapshot(call):
            entry_id = call.data.get("entry_id")
            inst = hass.data.get(DOMAIN, {}).get(entry_id)
            if inst is not None:
                inst.snapshot()
            else:
                _LOGGER.warning("Optimizer entry %s not found", entry_id)

        hass.services.async_register(
            DOMAIN, SERVICE_TAKE_SNAPSHOT, _handle_snapshot, schema=TAKE_SNAPSHOT_SCHEMA
        )

    return True


async def _async_update_listener(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Handle options update by reloading the entry."""
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        optimizer = hass.data.get(DOMAIN, {}).pop(entry.entry_id, None)
        if optimizer is not None:
            await optimizer.async_unload()
        if not hass.data.get(DOMAIN):
            hass.services.async_remove(DOMAIN, SERVICE_TAKE_SNAPSHOT)
    return unload_ok
