"""Number platform for Water Heater Optimizer."""

from homeassistant.components.number import NumberEntity, NumberMode
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import (
    CONF_HOT_WATER_RATIO,
    CONF_TARGET_TEMP,
    DEFAULT_RATIO,
    DEFAULT_TARGET_TEMP,
    DOMAIN,
    SIGNAL_UPDATE,
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up numbers."""
    optimizer = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([TargetTempNumber(optimizer, entry), HotWaterRatioNumber(optimizer, entry)])


class _OptimizerNumber(NumberEntity):
    """Base: dispatcher-driven number bound to one live config key.

    取值读 optimizer.config（options 优先），写入走 set_live_config 落到
    entry.options 持久化，重启不丢；仅这些键变化时 update listener 热应用，
    不重载条目。范围与 config_flow 里的选择器保持一致。
    """

    _attr_should_poll = False

    CONFIG_KEY: str
    DEFAULT: float
    TITLE_SUFFIX: str
    UNIQUE_SUFFIX: str

    def __init__(self, optimizer, entry: ConfigEntry):
        self._optimizer = optimizer
        self._entry = entry
        self._attr_name = f"{entry.title} {self.TITLE_SUFFIX}"
        self._attr_unique_id = f"{entry.entry_id}_{self.UNIQUE_SUFFIX}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name=entry.title,
            manufacturer="Water Heater Optimizer",
        )

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
    def native_value(self) -> float | None:
        return self._optimizer.config.get(self.CONFIG_KEY, self.DEFAULT)

    async def async_set_native_value(self, value: float) -> None:
        """Snap to step, clamp to range, then persist via the optimizer."""
        step = self.native_step or 1.0
        lo = self.native_min_value
        snapped = lo + round((float(value) - lo) / step) * step
        snapped = min(max(snapped, lo), self.native_max_value)
        self._optimizer.set_live_config(self.CONFIG_KEY, round(snapped, 2))
        # 吸附后与现值相同时 async_update_entry 是 no-op（无 listener/无
        # dispatcher），主动写一次状态，避免 UI 停在未吸附的输入值上
        self.async_write_ha_state()


class TargetTempNumber(_OptimizerNumber):
    """Shower target temperature (live-tunable)."""

    CONFIG_KEY = CONF_TARGET_TEMP
    DEFAULT = DEFAULT_TARGET_TEMP
    TITLE_SUFFIX = "Target Temperature"
    UNIQUE_SUFFIX = "target_temp"

    _attr_icon = "mdi:shower-head"
    _attr_native_min_value = 30.0
    _attr_native_max_value = 60.0
    _attr_native_step = 1.0
    _attr_native_unit_of_measurement = "°C"
    _attr_mode = NumberMode.BOX


class HotWaterRatioNumber(_OptimizerNumber):
    """Hot water ratio (live-tunable)."""

    CONFIG_KEY = CONF_HOT_WATER_RATIO
    DEFAULT = DEFAULT_RATIO
    TITLE_SUFFIX = "Hot Water Ratio"
    UNIQUE_SUFFIX = "hot_water_ratio"

    _attr_icon = "mdi:water-percent"
    _attr_native_min_value = 0.3
    _attr_native_max_value = 0.95
    _attr_native_step = 0.05
    _attr_mode = NumberMode.SLIDER
