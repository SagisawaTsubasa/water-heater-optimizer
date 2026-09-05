"""Sensor platform for Water Heater Optimizer."""

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity, SensorStateClass
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import STATE_UNAVAILABLE, STATE_UNKNOWN
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.restore_state import RestoreEntity

from .const import DOMAIN, ATTR_REFERENCE_TAP_TEMP, SIGNAL_UPDATE


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


def _device_info(entry: ConfigEntry) -> DeviceInfo:
    return DeviceInfo(
        identifiers={(DOMAIN, entry.entry_id)},
        name=entry.title,
        manufacturer="Water Heater Optimizer",
    )


class _OptimizerSensor(SensorEntity, RestoreEntity):
    """Base: dispatcher-driven sensor that restores its value after restart."""

    _attr_should_poll = False
    _attr_native_unit_of_measurement = "°C"
    _attr_device_class = SensorDeviceClass.TEMPERATURE
    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(self, optimizer, entry: ConfigEntry):
        self._optimizer = optimizer
        self._entry = entry
        self._attr_name = f"{entry.title} {self.TITLE_SUFFIX}"
        self._attr_unique_id = f"{entry.entry_id}_{self.UNIQUE_SUFFIX}"
        self._attr_device_info = _device_info(entry)
        self._restored = None

    async def async_added_to_hass(self):
        """Register update dispatcher and restore last value."""
        self.async_on_remove(
            async_dispatcher_connect(
                self.hass,
                f"{SIGNAL_UPDATE}_{self._entry.entry_id}",
                self.async_write_ha_state,
            )
        )
        # 重启后先恢复上次读数，避免在下次快照前一直 unknown
        last_state = await self.async_get_last_state()
        if last_state is not None and last_state.state not in (
            STATE_UNKNOWN,
            STATE_UNAVAILABLE,
        ):
            try:
                self._restored = round(float(last_state.state), 1)
            except (TypeError, ValueError):
                pass

    @property
    def native_value(self):
        current = self._current_value()
        if current is not None:
            return current
        return self._restored

    def _current_value(self):
        raise NotImplementedError


class RecommendedTempSensor(_OptimizerSensor):
    """Recommended heater temperature."""

    TITLE_SUFFIX = "Recommended Temperature"
    UNIQUE_SUFFIX = "recommended_temp"
    _attr_icon = "mdi:thermometer-chevron-up"

    def _current_value(self):
        return self._optimizer.recommended_temp

    @property
    def extra_state_attributes(self):
        return {
            ATTR_REFERENCE_TAP_TEMP: self._optimizer.reference_tap_temp,
            "applied_temp": self._optimizer.applied_temp,
        }


class ReferenceTapTempSensor(_OptimizerSensor):
    """Reference tap water temperature from last snapshot."""

    TITLE_SUFFIX = "Reference Tap Temperature"
    UNIQUE_SUFFIX = "reference_tap_temp"
    _attr_icon = "mdi:water-thermometer"

    def _current_value(self):
        return self._optimizer.reference_tap_temp
