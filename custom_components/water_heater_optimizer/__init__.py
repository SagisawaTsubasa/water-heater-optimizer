"""Water Heater Optimizer integration."""

import logging
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.typing import ConfigType

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

PLATFORMS = ["sensor", "switch"]


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Set up the integration."""
    hass.data.setdefault(DOMAIN, {})
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up a config entry."""
    from .optimizer import WaterHeaterOptimizer

    optimizer = WaterHeaterOptimizer(hass, entry)
    hass.data[DOMAIN][entry.entry_id] = optimizer
    await optimizer.async_setup()

    # Reload the entry automatically when options are changed
    entry.async_on_unload(entry.add_update_listener(_async_update_listener))

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    if not hass.services.has_service(DOMAIN, "take_snapshot"):
        async def _handle_snapshot(call):
            entry_id = call.data.get("entry_id")
            inst = hass.data[DOMAIN].get(entry_id)
            if inst:
                inst.snapshot()
            else:
                _LOGGER.warning("Optimizer entry %s not found", entry_id)

        hass.services.async_register(DOMAIN, "take_snapshot", _handle_snapshot)

    return True


async def _async_update_listener(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Handle options update by reloading the entry."""
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        optimizer = hass.data[DOMAIN].pop(entry.entry_id, None)
        if optimizer:
            await optimizer.async_unload()
    return unload_ok
