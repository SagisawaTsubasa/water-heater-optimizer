"""Core optimizer logic."""

import logging
import time

from homeassistant.const import STATE_UNAVAILABLE, STATE_UNKNOWN
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.event import (
    async_call_later,
    async_track_state_change_event,
    async_track_time_change,
)
from homeassistant.helpers.dispatcher import async_dispatcher_send

from .const import (
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
    DEFAULT_TRIGGER_TIME,
    TRIGGER_TYPE_ENTITY_STATE,
    TRIGGER_TYPE_DURATION,
    TRIGGER_TYPE_FIXED_TIME,
    SIGNAL_UPDATE,
)

_LOGGER = logging.getLogger(__name__)


class WaterHeaterOptimizer:
    """Manage temperature optimization for a single water heater."""

    # 差值不超过该阈值时不下发设定温度（防止属性更新风暴）(H3)
    APPLY_HYSTERESIS_C = 1.0
    # 两次下发之间的最小间隔（秒）
    APPLY_COOLDOWN_S = 300

    def __init__(self, hass: HomeAssistant, entry):
        self.hass = hass
        self.entry = entry
        # Options (re-configured values) take priority over initial setup data
        self.config = {**entry.data, **entry.options}
        self.recommended_temp = None
        self.reference_tap_temp = None
        self.auto_adjust = False
        self.applied_temp = None
        self._listeners = []
        self._duration_timer = None
        self._apply_task = None
        self._last_apply_mono = None
        self._signal = f"{SIGNAL_UPDATE}_{entry.entry_id}"

    def calculate(self, tap_temp: float | None) -> int | None:
        """Calculate recommended heater temperature."""
        if tap_temp is None:
            return None

        target = self.config.get(CONF_TARGET_TEMP, DEFAULT_TARGET_TEMP)
        ratio = self.config.get(CONF_HOT_WATER_RATIO, DEFAULT_RATIO)
        min_temp = self.config.get(CONF_MIN_TEMP, DEFAULT_MIN_TEMP)
        max_temp = self.config.get(CONF_MAX_TEMP, DEFAULT_MAX_TEMP)

        try:
            ratio = float(ratio)
            min_temp = float(min_temp)
            max_temp = float(max_temp)
        except (TypeError, ValueError):
            _LOGGER.warning("非法的温度/比例配置，跳过计算")
            return None
        if ratio <= 0:
            # 手工改 storage 可能绕过选择器范围 (L7)
            _LOGGER.warning("热水比例必须大于 0（当前 %s），跳过计算", ratio)
            return None
        if min_temp > max_temp:
            min_temp, max_temp = max_temp, min_temp

        rec = tap_temp + (target - tap_temp) / ratio
        if rec < min_temp:
            rec = min_temp
        elif rec > max_temp:
            rec = max_temp
        return round(rec)

    async def async_setup(self):
        """Set up triggers based on configuration."""
        trigger_type = self.config.get(CONF_TRIGGER_TYPE, TRIGGER_TYPE_ENTITY_STATE)

        if trigger_type == TRIGGER_TYPE_ENTITY_STATE:
            await self._setup_entity_state_trigger()
        elif trigger_type == TRIGGER_TYPE_DURATION:
            await self._setup_duration_trigger()
        elif trigger_type == TRIGGER_TYPE_FIXED_TIME:
            await self._setup_fixed_time_trigger()
        else:
            _LOGGER.warning("未知触发类型 %r，未注册任何触发器", trigger_type)

    async def async_unload(self):
        """Remove all listeners and pending work."""
        for unsub in self._listeners:
            unsub()
        self._listeners.clear()
        self._cancel_duration_timer()
        if self._apply_task is not None and not self._apply_task.done():
            self._apply_task.cancel()

    def _cancel_duration_timer(self):
        if self._duration_timer is not None:
            self._duration_timer()
            self._duration_timer = None

    async def _setup_entity_state_trigger(self):
        """Trigger on entity state change."""
        entity = self.config.get(CONF_TRIGGER_ENTITY) or self.config[CONF_INLET_TEMP_SENSOR]
        from_state = self.config.get(CONF_TRIGGER_FROM_STATE)
        to_state = self.config.get(CONF_TRIGGER_TO_STATE)

        @callback
        def _state_changed(event):
            old = event.data.get("old_state")
            new = event.data.get("new_state")

            # HA 重启后的首条事件 old 可能为 None：配置了 from_state 时跳过
            # 这一条是刻意行为，避免把未知起点当作有效来源状态
            if from_state and (old is None or old.state != from_state):
                return
            if to_state and (new is None or new.state != to_state):
                return

            self.snapshot()

        self._listeners.append(
            async_track_state_change_event(self.hass, entity, _state_changed)
        )

    async def _setup_duration_trigger(self):
        """Trigger after entity has been in a state for a duration."""
        entity = self.config.get(CONF_TRIGGER_ENTITY) or self.config[CONF_INLET_TEMP_SENSOR]
        to_state = self.config.get(CONF_TRIGGER_TO_STATE)
        duration = self.config.get(CONF_TRIGGER_DURATION, 120)

        def _schedule():
            # 先取消旧定时器再挂新的：同一状态的重复事件（属性更新等）
            # 不再堆叠 N 个到期快照 (H2)
            self._cancel_duration_timer()
            self._duration_timer = async_call_later(
                self.hass, duration, lambda _now: self.snapshot()
            )

        @callback
        def _state_changed(event):
            new = event.data.get("new_state")
            if new is None:
                return

            if to_state and new.state != to_state:
                self._cancel_duration_timer()
                return

            # 已处于目标状态的重复事件不重挂定时器（纯属性更新会反复触发）
            old = event.data.get("old_state")
            if to_state and old is not None and old.state == to_state:
                return

            _schedule()

        self._listeners.append(
            async_track_state_change_event(self.hass, entity, _state_changed)
        )

        # 启动/重载时实体已处于目标状态：同样要安排快照，
        # 否则直到下一次状态翻转前当日优化会静默缺失 (M4)
        state = self.hass.states.get(entity)
        if state is not None and (not to_state or state.state == to_state):
            _LOGGER.debug("%s already in target state at startup, scheduling snapshot", entity)
            _schedule()

    async def _setup_fixed_time_trigger(self):
        """Trigger at a fixed time every day."""
        time_str = self.config.get(CONF_TRIGGER_TIME, DEFAULT_TRIGGER_TIME)
        try:
            # TimeSelector 输出 "HH:MM:SS" (H1)
            parts = time_str.split(":")
            hour, minute = int(parts[0]), int(parts[1])
        except (ValueError, IndexError, AttributeError):
            _LOGGER.warning("无法解析触发时间 %r，回落到 06:00", time_str)
            hour, minute = 6, 0

        @callback
        def _time_trigger(now):
            self.snapshot()

        self._listeners.append(
            async_track_time_change(self.hass, _time_trigger, hour=hour, minute=minute)
        )

    def snapshot(self):
        """Read inlet temperature and update reference."""
        sensor = self.config[CONF_INLET_TEMP_SENSOR]
        state = self.hass.states.get(sensor)
        if state is None or state.state in (STATE_UNKNOWN, STATE_UNAVAILABLE, "none", ""):
            _LOGGER.debug("Inlet sensor %s unavailable, skipping snapshot", sensor)
            return

        try:
            tap_temp = float(state.state)
        except (ValueError, TypeError):
            _LOGGER.warning("Invalid inlet temperature value: %s", state.state)
            return

        self.reference_tap_temp = tap_temp
        self.recommended_temp = self.calculate(tap_temp)
        _LOGGER.info(
            "Snapshot taken: tap=%.1f°C, recommended=%s°C",
            tap_temp,
            self.recommended_temp,
        )

        async_dispatcher_send(self.hass, self._signal)

        if self.auto_adjust and self.recommended_temp is not None:
            # 保存任务引用，卸载时可取消 (M2)
            self._apply_task = self.hass.async_create_task(self._apply_temperature())

    async def _apply_temperature(self) -> bool:
        """Apply recommended temperature to water heater.

        带迟滞与冷却：当前设定已接近推荐值、或距上次下发太近时跳过，
        避免进水温度传感器每次上报都向热水器发一条 set_temperature (H3)。
        Returns True when a command was actually sent.
        """
        heater = self.config[CONF_WATER_HEATER]
        now_mono = time.monotonic()
        if (
            self._last_apply_mono is not None
            and (now_mono - self._last_apply_mono) < self.APPLY_COOLDOWN_S
        ):
            _LOGGER.debug("下发冷却期内，跳过 set_temperature")
            return False

        target = self.recommended_temp
        heater_state = self.hass.states.get(heater)
        if heater_state is not None:
            # 按目标设备自身限值夹紧 (M2)
            try:
                lo = heater_state.attributes.get("min_temp")
                hi = heater_state.attributes.get("max_temp")
                if lo is not None:
                    target = max(target, int(float(lo)))
                if hi is not None:
                    target = min(target, int(float(hi)))
            except (TypeError, ValueError):
                pass
            current = heater_state.attributes.get("temperature")
            try:
                if current is not None and abs(float(current) - target) <= self.APPLY_HYSTERESIS_C:
                    _LOGGER.debug(
                        "热水器当前设定 %.1f°C 与推荐值差值在迟滞范围内，跳过下发",
                        float(current),
                    )
                    return False
            except (TypeError, ValueError):
                pass
        try:
            await self.hass.services.async_call(
                "water_heater",
                "set_temperature",
                {
                    "entity_id": heater,
                    "temperature": target,
                },
                blocking=True,
            )
        except HomeAssistantError as err:
            _LOGGER.error("下发设定温度到 %s 失败: %s", heater, err)
            return False

        self._last_apply_mono = now_mono
        self.applied_temp = target
        async_dispatcher_send(self.hass, self._signal)
        return True

    async def async_set_auto_adjust(self, enabled: bool):
        """Enable or disable auto-adjust."""
        self.auto_adjust = enabled
        if enabled and self.recommended_temp is not None:
            await self._apply_temperature()
        async_dispatcher_send(self.hass, self._signal)
