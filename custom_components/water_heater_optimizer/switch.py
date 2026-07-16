"""Switch platform for Water Heater Optimizer."""

from homeassistant.components.switch import SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.dispatcher import async_dispatcher_connect

from .const import DOMAIN, SIGNAL_UPDATE


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up switch."""
    optimizer = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([AutoAdjustSwitch(optimizer, entry)])


class AutoAdjustSwitch(SwitchEntity):
    """Toggle auto-adjustment of water heater temperature."""

    def __init__(self, optimizer, entry):
        self._optimizer = optimizer
        self._entry = entry
        self._attr_name = f"{entry.title} Auto Adjust"
        self._attr_unique_id = f"{entry.entry_id}_auto_adjust"
        self._attr_icon = "mdi:thermometer-auto"

    async def async_added_to_hass(self):
        """Register update dispatcher."""
        self.async_on_remove(
            async_dispatcher_connect(
                self.hass,
                f"{SIGNAL_UPDATE}_{self._entry.entry_id}",
                self.async_write_ha_state,
            )
        )

    @property
    def is_on(self):
        return self._optimizer.auto_adjust

    async def async_turn_on(self, **kwargs):
        await self._optimizer.async_set_auto_adjust(True)

    async def async_turn_off(self, **kwargs):
        await self._optimizer.async_set_auto_adjust(False)
