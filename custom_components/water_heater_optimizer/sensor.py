"""Sensor platform for Water Heater Optimizer."""

from homeassistant.components.sensor import SensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.dispatcher import async_dispatcher_connect

from .const import DOMAIN, ATTR_RECOMMENDED_TEMP, ATTR_REFERENCE_TAP_TEMP, SIGNAL_UPDATE


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up sensors."""
    optimizer = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([
        RecommendedTempSensor(optimizer, entry),
        ReferenceTapTempSensor(optimizer, entry),
    ])


class RecommendedTempSensor(SensorEntity):
    """Recommended heater temperature."""

    def __init__(self, optimizer, entry):
        self._optimizer = optimizer
        self._entry = entry
        self._attr_name = f"{entry.title} Recommended Temperature"
        self._attr_unique_id = f"{entry.entry_id}_recommended_temp"
        self._attr_native_unit_of_measurement = "°C"
        self._attr_device_class = "temperature"
        self._attr_state_class = "measurement"
        self._attr_icon = "mdi:thermometer-chevron-up"

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
    def native_value(self):
        return self._optimizer.recommended_temp

    @property
    def extra_state_attributes(self):
        return {
            ATTR_REFERENCE_TAP_TEMP: self._optimizer.reference_tap_temp,
        }


class ReferenceTapTempSensor(SensorEntity):
    """Reference tap water temperature from last snapshot."""

    def __init__(self, optimizer, entry):
        self._optimizer = optimizer
        self._entry = entry
        self._attr_name = f"{entry.title} Reference Tap Temperature"
        self._attr_unique_id = f"{entry.entry_id}_reference_tap_temp"
        self._attr_native_unit_of_measurement = "°C"
        self._attr_device_class = "temperature"
        self._attr_state_class = "measurement"
        self._attr_icon = "mdi:water-thermometer"

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
    def native_value(self):
        return self._optimizer.reference_tap_temp
