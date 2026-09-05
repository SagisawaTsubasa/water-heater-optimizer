"""Switch platform for Water Heater Optimizer."""

from homeassistant.components.switch import SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.restore_state import RestoreEntity

from .const import DOMAIN, SIGNAL_UPDATE


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up switch."""
    optimizer = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([AutoAdjustSwitch(optimizer, entry)])


class AutoAdjustSwitch(SwitchEntity, RestoreEntity):
    """Toggle auto-adjustment of water heater temperature."""

    _attr_should_poll = False
    _attr_icon = "mdi:thermometer-auto"

    def __init__(self, optimizer, entry: ConfigEntry):
        self._optimizer = optimizer
        self._entry = entry
        self._attr_name = f"{entry.title} Auto Adjust"
        self._attr_unique_id = f"{entry.entry_id}_auto_adjust"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name=entry.title,
            manufacturer="Water Heater Optimizer",
        )

    async def async_added_to_hass(self):
        """Register update dispatcher and restore last state."""
        self.async_on_remove(
            async_dispatcher_connect(
                self.hass,
                f"{SIGNAL_UPDATE}_{self._entry.entry_id}",
                self.async_write_ha_state,
            )
        )
        # Restore auto-adjust flag across HA restarts; unavailable/unknown
        # states are ignored instead of silently switching it off.
        if (last_state := await self.async_get_last_state()) is not None and (
            last_state.state in ("on", "off")
        ):
            self._optimizer.auto_adjust = last_state.state == "on"
            self.async_write_ha_state()

    @property
    def is_on(self):
        return self._optimizer.auto_adjust

    async def async_turn_on(self, **kwargs):
        await self._optimizer.async_set_auto_adjust(True)

    async def async_turn_off(self, **kwargs):
        await self._optimizer.async_set_auto_adjust(False)
