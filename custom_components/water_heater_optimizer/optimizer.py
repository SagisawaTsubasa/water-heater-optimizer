"""Core optimizer logic."""

import asyncio
import logging
import math
import time

from homeassistant.const import STATE_UNAVAILABLE, STATE_UNKNOWN
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.dispatcher import async_dispatcher_send
from homeassistant.helpers.event import (
    async_call_later,
    async_track_state_change_event,
    async_track_time_change,
)
from homeassistant.helpers.start import async_at_started

from .const import (
    CONF_HOT_WATER_RATIO,
    CONF_INLET_TEMP_SENSOR,
    CONF_MAX_TEMP,
    CONF_MIN_TEMP,
    CONF_TARGET_TEMP,
    CONF_TRIGGER_DURATION,
    CONF_TRIGGER_ENTITY,
    CONF_TRIGGER_FROM_STATE,
    CONF_TRIGGER_TIME,
    CONF_TRIGGER_TO_STATE,
    CONF_TRIGGER_TYPE,
    CONF_WATER_HEATER,
    DEFAULT_MAX_TEMP,
    DEFAULT_MIN_TEMP,
    DEFAULT_RATIO,
    DEFAULT_TARGET_TEMP,
    DEFAULT_TRIGGER_TIME,
    SIGNAL_UPDATE,
    TRIGGER_TYPE_DURATION,
    TRIGGER_TYPE_ENTITY_STATE,
    TRIGGER_TYPE_FIXED_TIME,
)

_LOGGER = logging.getLogger(__name__)


class WaterHeaterOptimizer:
    """Manage temperature optimization for a single water heater."""

    # 差值不超过该阈值时不下发设定温度（防止属性更新风暴）(H3)
    APPLY_HYSTERESIS_C = 1.0
    # 两次下发之间的最小间隔（秒）
    APPLY_COOLDOWN_S = 300
    # 热应用 forced 下发的去抖（秒）：合并同轮/连续的参数写入
    LIVE_APPLY_DEBOUNCE_S = 1.5

    def __init__(self, hass: HomeAssistant, entry):
        self.hass = hass
        self.entry = entry
        # Options (re-configured values) take priority over initial setup data
        self.config = {**entry.data, **entry.options}
        # update listener 用来 diff 前后 options/title/data，判断是热应用还是重载
        self.last_options = dict(entry.options)
        self.last_data = dict(entry.data)
        self.last_title = entry.title
        self.recommended_temp = None
        self.reference_tap_temp = None
        self.auto_adjust = False
        self.applied_temp = None
        self._listeners = []
        self._duration_timer = None
        self._live_apply_timer = None
        self._apply_tasks: set[asyncio.Task] = set()
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
            _LOGGER.debug("推荐值 %.1f°C 低于窗口下限 %.1f°C，夹紧", rec, min_temp)
            rec = min_temp
        elif rec > max_temp:
            _LOGGER.debug("推荐值 %.1f°C 高于窗口上限 %.1f°C，夹紧", rec, max_temp)
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
        self._cancel_live_apply_timer()
        for task in self._apply_tasks:
            task.cancel()

    def _spawn_apply(self, coro) -> None:
        """创建下发任务并统一跟踪。

        单槽引用会被后续任务覆盖，更早的在飞任务会逃过卸载取消；
        集合 + done_callback 自动清位，卸载时全部 cancel。
        """
        task = self.hass.async_create_task(coro)
        self._apply_tasks.add(task)
        task.add_done_callback(self._apply_tasks.discard)

    def _cancel_live_apply_timer(self):
        if self._live_apply_timer is not None:
            self._live_apply_timer()
            self._live_apply_timer = None

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

        # 启动/重载后补拍一次快照 (M4)：否则要等实体下一次状态变化才有数据，
        # 进水温度夜间几乎不变，传感器会长期停在 unknown。
        # 经 async_at_started 延后到 HA 启动完成（重载时已启动则立即回调），
        # 避免在 setup 期其他集成实体尚未恢复状态时白拍。
        # 启动时不存在状态转移，from_state（离开来源）无从判定——只要当前
        # 不停在 from_state 且满足 to_state 即补拍；snapshot() 自带
        # unavailable/unknown 防御。注意 auto_adjust 此时恒为 False（开关
        # 恢复发生在平台转发阶段且直接赋值，不走 async_set_auto_adjust），
        # 因此补拍绝不会导致重启即下发。
        @callback
        def _at_started_cb(_hass):
            self._startup_snapshot(entity, from_state, to_state)

        # 回调必须 @callback：裸函数/lambda 会被 HA 判为 Executor job 放进
        # 线程池执行，snapshot 里的 dispatcher 与实体刷新会触发跨线程
        # RuntimeError（HA 2026.1 起 frame 检查直抛）。下同，不逐一重复
        self._listeners.append(async_at_started(self.hass, _at_started_cb))

    @callback
    def _startup_snapshot(self, entity: str, from_state: str | None, to_state: str | None):
        """Take one snapshot after HA started if the current state qualifies."""
        current = self.hass.states.get(entity)
        if current is None:
            _LOGGER.debug("启动补拍跳过：%s 尚无状态（等首次状态事件）", entity)
            return
        if (to_state and current.state != to_state) or (
            from_state and current.state == from_state
        ):
            _LOGGER.debug(
                "启动补拍跳过：%s 当前 %s 不满足过滤 (from=%r, to=%r)",
                entity, current.state, from_state, to_state,
            )
            return
        try:
            self.snapshot()
        except Exception:
            _LOGGER.exception("启动补拍失败（已忽略，等下次状态事件）")

    async def _setup_duration_trigger(self):
        """Trigger after entity has been in a state for a duration."""
        entity = self.config.get(CONF_TRIGGER_ENTITY) or self.config[CONF_INLET_TEMP_SENSOR]
        to_state = self.config.get(CONF_TRIGGER_TO_STATE)
        duration = self.config.get(CONF_TRIGGER_DURATION, 120)

        @callback
        def _fire_snapshot(_now):
            self.snapshot()

        def _schedule():
            # 先取消旧定时器再挂新的：同一状态的重复事件（属性更新等）
            # 不再堆叠 N 个到期快照 (H2)
            self._cancel_duration_timer()
            self._duration_timer = async_call_later(self.hass, duration, _fire_snapshot)

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

    @callback
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
        if not math.isfinite(tap_temp):
            _LOGGER.warning("Non-finite inlet temperature %r, skipping snapshot", state.state)
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
            if self._live_apply_timer is not None:
                # 热应用去抖窗口内：待发的 forced 下发执行时读到的正是这里
                # 刚算出的最新推荐值，合并成一次下发即可
                _LOGGER.debug("热应用去抖窗口内，快照下发与 forced 下发合并")
                return
            self._spawn_apply(self._apply_temperature())

    async def _apply_temperature(self, force: bool = False) -> bool:
        """Apply recommended temperature to water heater.

        带迟滞与冷却：当前设定已接近推荐值、或距上次下发太近时跳过，
        避免进水温度传感器每次上报都向热水器发一条 set_temperature (H3)。
        force=True 跳过冷却但保留迟滞（用于用户主动改参数后的立即下发）。
        Returns True when a command was actually sent.
        """
        heater = self.config[CONF_WATER_HEATER]
        now_mono = time.monotonic()
        if (
            not force
            and self._last_apply_mono is not None
            and (now_mono - self._last_apply_mono) < self.APPLY_COOLDOWN_S
        ):
            _LOGGER.debug("下发冷却期内，跳过 set_temperature")
            return False

        target = self.recommended_temp
        heater_state = self.hass.states.get(heater)
        if heater_state is None:
            # 热水器实体缺席时无法夹紧设备限值也无法做迟滞比较，
            # 盲发原始推荐值有风险——记日志跳过，等下一次快照重试
            _LOGGER.debug("热水器 %s 状态缺席，跳过下发", heater)
            return False
        # 按目标设备自身限值夹紧 (M2)
        try:
            lo = heater_state.attributes.get("min_temp")
            hi = heater_state.attributes.get("max_temp")
            if lo is not None:
                target = max(target, math.ceil(float(lo)))
            if hi is not None:
                target = min(target, math.floor(float(hi)))
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

    def set_live_config(self, key: str, value) -> None:
        """把可调参数写入 entry.options（持久化，重启后保留）。

        不在这里热应用：update listener 会 diff 前后 options，
        只有可调参数变化时调 apply_live_config()，否则照常重载条目。
        值未变化时 async_update_entry 是 no-op，不会触发 listener。
        """
        self.hass.config_entries.async_update_entry(
            self.entry, options={**self.entry.options, key: value}
        )

    def apply_live_config(self):
        """热应用可调参数（target_temp / hot_water_ratio），不重载条目。

        用最近一次快照的进水温度重算推荐值；自动调节开启时立即下发
        （绕过下发冷却——这是用户主动动作，不是传感器风暴；迟滞与
        设备限值夹紧仍然生效，避免无意义的重复 set_temperature）。
        """
        self.config = {**self.entry.data, **self.entry.options}
        self.last_options = dict(self.entry.options)
        self.last_data = dict(self.entry.data)
        self.last_title = self.entry.title
        if self.reference_tap_temp is not None:
            self.recommended_temp = self.calculate(self.reference_tap_temp)
            _LOGGER.info(
                "参数已热更新: target=%s°C, ratio=%s → recommended=%s°C",
                self.config.get(CONF_TARGET_TEMP),
                self.config.get(CONF_HOT_WATER_RATIO),
                self.recommended_temp,
            )
        async_dispatcher_send(self.hass, self._signal)
        if self.auto_adjust and self.recommended_temp is not None:
            # forced 下发做短去抖：连续多次参数写入（脚本并行、前端连续上报）
            # 只保留最后一次，避免多个任务在热水器回读温度前全部通过迟滞检查、
            # 各发一条真实 set_temperature；卸载时连定时器带任务一起取消
            self._cancel_live_apply_timer()
            self._live_apply_timer = async_call_later(
                self.hass, self.LIVE_APPLY_DEBOUNCE_S, self._fire_live_apply
            )

    @callback
    def _fire_live_apply(self, _now) -> None:
        self._live_apply_timer = None
        if not self.auto_adjust:
            # 去抖窗口内用户关掉了自动调节，撤单
            return
        self._spawn_apply(self._apply_temperature(force=True))

    async def async_set_auto_adjust(self, enabled: bool):
        """Enable or disable auto-adjust."""
        self.auto_adjust = enabled
        if not enabled:
            # 去抖窗口内改参数又关开关：撤掉挂起的 forced 下发
            self._cancel_live_apply_timer()
        if enabled and self.recommended_temp is not None:
            await self._apply_temperature()
        async_dispatcher_send(self.hass, self._signal)
