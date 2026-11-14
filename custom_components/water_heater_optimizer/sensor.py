"""Sensor platform for Water Heater Optimizer."""

import logging

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import STATE_UNAVAILABLE, STATE_UNKNOWN
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.restore_state import RestoreEntity

from .const import CONF_INLET_TEMP_SENSOR, DOMAIN, SIGNAL_UPDATE

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up sensors."""
    optimizer = hass.data[DOMAIN][entry.entry_id]
    _remove_stale_reference_tap_entity(hass, entry)
    async_add_entities([RecommendedTempSensor(optimizer, entry)])


def _remove_stale_reference_tap_entity(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """清掉 v0.3.0 砍除的 ReferenceTapTempSensor 注册表残留（R1 P3#8）。

    平台不再提供该实体后 HA 不会自动清注册表，升级用户会留一个永久
    unavailable 的幽灵实体（WHA-F-332 同型）。幂等：清完后
    async_get_entity_id 返回 None，后续 setup 空跑。
    """
    registry = er.async_get(hass)
    stale = registry.async_get_entity_id(
        "sensor", DOMAIN, f"{entry.entry_id}_reference_tap_temp"
    )
    if stale is not None:
        registry.async_remove(stale)
        _LOGGER.info("已清理旧版 Reference Tap 实体注册表条目 %s", stale)


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
        # 重启后先恢复上次读数，避免在下次均值变化前一直 unknown
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
            # avg 源实体指针（24h 均值 filter 实体）：从实体详情页可直达数据源
            "inlet_temp_sensor": self._optimizer.config.get(CONF_INLET_TEMP_SENSOR),
            "applied_temp": self._optimizer.applied_temp,
        }
