"""Number platform for Water Heater Optimizer."""

import logging
import math

from homeassistant.components.number import NumberEntity, NumberMode
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import (
    CONF_HOT_WATER_RATIO,
    CONF_MAX_TEMP,
    CONF_MIN_TEMP,
    CONF_TARGET_TEMP,
    DEFAULT_MAX_TEMP,
    DEFAULT_MIN_TEMP,
    DEFAULT_RATIO,
    DEFAULT_TARGET_TEMP,
    DOMAIN,
    SIGNAL_UPDATE,
)

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up numbers."""
    optimizer = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([
        TargetTempNumber(optimizer, entry),
        HotWaterRatioNumber(optimizer, entry),
        MinTempNumber(optimizer, entry),
        MaxTempNumber(optimizer, entry),
    ])


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
        self._validate_window(snapped)
        self._optimizer.set_live_config(self.CONFIG_KEY, round(snapped, 2))
        # 吸附后与现值相同时 async_update_entry 是 no-op（无 listener/无
        # dispatcher），主动写一次状态，避免 UI 停在未吸附的输入值上
        self.async_write_ha_state()

    def _validate_window(self, value: float) -> None:
        """推荐窗口上下限写入前的 min<max 交叉校验（R1 P2#1）。

        仅 Min/Max 两类生效（按既有 CONFIG_KEY 判定，不新增角色属性）；
        等值也拒，与表单 invalid_range（min >= max）语义对齐；拦截时抛
        走翻译体系的 HomeAssistantError（invalid_window，R3-fix F-576）
        且不落 options。sibling 不可解析或非有限（手工改 storage 的坏值
        路径）时落 WARNING 放行——交叉约束无从判定，坏值已由 calculate
        的非法配置 WARNING 兜底响，非静默回落（NaN 曾因 IEEE 比较恒
        False 静默绕过两个 raise，R3-fix F-575 补 isfinite 检查）。
        """
        if self.CONFIG_KEY == CONF_MIN_TEMP:
            sib_key, sib_default = CONF_MAX_TEMP, DEFAULT_MAX_TEMP
        elif self.CONFIG_KEY == CONF_MAX_TEMP:
            sib_key, sib_default = CONF_MIN_TEMP, DEFAULT_MIN_TEMP
        else:
            return  # TargetTemp/Ratio 与窗口无耦合，不做跨项约束
        # sibling 读 entry.options 优先 data 兜底（与 config_flow _current 同源
        # 同序）：optimizer.config 要等 update listener 热应用才重建，连续两
        # 次写入会读到滞后值，等值倒置可能漏拦
        raw_sibling = self._entry.options.get(
            sib_key, self._entry.data.get(sib_key, sib_default)
        )
        try:
            sib_val = float(raw_sibling)
        except (TypeError, ValueError):
            _LOGGER.warning(
                "存量 %s 值 %r 不可解析，跳过本次窗口交叉校验", sib_key, raw_sibling
            )
            return
        if not math.isfinite(sib_val):
            # R3-fix F-575：NaN 转换成功但 IEEE 比较（>=/<=）恒 False，
            # 会静默绕过下方两个 raise——非有限值同样无从交叉判定，
            # WARNING 后放行，坏值由 calculate 的 isfinite 守卫兜底响
            _LOGGER.warning(
                "存量 %s 值 %r 非有限数，跳过本次窗口交叉校验", sib_key, raw_sibling
            )
            return
        # R3-fix F-576：文案走 HA 异常翻译（exceptions.invalid_window）——
        # placeholders 命名为 min_temp/max_temp，min/max 两个写入方向陈述
        # 同一不变量；:g 显示口径沿用原硬编码文案
        placeholders = {
            "min_temp": f"{value if self.CONFIG_KEY == CONF_MIN_TEMP else sib_val:g}",
            "max_temp": f"{sib_val if self.CONFIG_KEY == CONF_MIN_TEMP else value:g}",
        }
        if self.CONFIG_KEY == CONF_MIN_TEMP and value >= sib_val:
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="invalid_window",
                translation_placeholders=placeholders,
            )
        if self.CONFIG_KEY == CONF_MAX_TEMP and value <= sib_val:
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="invalid_window",
                translation_placeholders=placeholders,
            )


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


class MinTempNumber(_OptimizerNumber):
    """Recommended setpoint minimum (live-tunable)."""

    CONFIG_KEY = CONF_MIN_TEMP
    DEFAULT = DEFAULT_MIN_TEMP
    TITLE_SUFFIX = "Recommended Minimum"
    UNIQUE_SUFFIX = "min_temp"

    _attr_icon = "mdi:thermometer-low"
    _attr_native_min_value = 30.0
    _attr_native_max_value = 60.0
    _attr_native_step = 1.0
    _attr_native_unit_of_measurement = "°C"
    _attr_mode = NumberMode.BOX


class MaxTempNumber(_OptimizerNumber):
    """Recommended setpoint maximum (live-tunable)."""

    CONFIG_KEY = CONF_MAX_TEMP
    DEFAULT = DEFAULT_MAX_TEMP
    TITLE_SUFFIX = "Recommended Maximum"
    UNIQUE_SUFFIX = "max_temp"

    _attr_icon = "mdi:thermometer-high"
    _attr_native_min_value = 30.0
    _attr_native_max_value = 70.0
    _attr_native_step = 1.0
    _attr_native_unit_of_measurement = "°C"
    _attr_mode = NumberMode.BOX
