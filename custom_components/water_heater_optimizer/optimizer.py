"""Core optimizer logic."""

import asyncio
import logging
import math

from homeassistant.const import STATE_UNAVAILABLE, STATE_UNKNOWN
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.dispatcher import async_dispatcher_send
from homeassistant.helpers.event import async_track_state_change_event

from .const import (
    CONF_HOT_WATER_RATIO,
    CONF_INLET_TEMP_SENSOR,
    CONF_MAX_TEMP,
    CONF_MIN_TEMP,
    CONF_TARGET_TEMP,
    CONF_WATER_HEATER,
    DEFAULT_MAX_TEMP,
    DEFAULT_MIN_TEMP,
    DEFAULT_RATIO,
    DEFAULT_TARGET_TEMP,
    SIGNAL_UPDATE,
)

_LOGGER = logging.getLogger(__name__)


class WaterHeaterOptimizer:
    """Manage temperature optimization for a single water heater.

    v2: 进水温度取自外部 24h 均值 filter 实体；仅当均值整数值变化时重算
    推荐值，auto_adjust 开且推荐值与热水器当前设定不同才下发 set_temperature。
    """

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
        self.last_avg_temp: int | None = None
        self.auto_adjust = False
        self.applied_temp = None
        self._listeners = []
        # 单飞：同一时刻至多一个下发任务在跑（R1 P2#5，防去抖移除后连发）
        self._apply_task: asyncio.Task | None = None
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
            # target 与其余参数同一 try（R1 P3#10）：storage 字符串/None 不再
            # 拖到 rec 计算行才炸回调
            target = float(target)
            ratio = float(ratio)
            min_temp = float(min_temp)
            max_temp = float(max_temp)
        except (TypeError, ValueError):
            _LOGGER.warning("非法的温度/比例配置，跳过计算")
            return None
        if not all(map(math.isfinite, (target, ratio, min_temp, max_temp))):
            # NaN ratio 会让 ratio<=0 恒 False 混过旧守卫、round(nan) 抛错
            _LOGGER.warning(
                "温度/比例配置含非有限值（target=%r ratio=%r min=%r max=%r），跳过计算",
                target, ratio, min_temp, max_temp,
            )
            return None
        if ratio <= 0:
            # 手工改 storage 可能绕过选择器范围 (L7)
            _LOGGER.warning("热水比例必须大于 0（当前 %s），跳过计算", ratio)
            return None
        if min_temp == max_temp:
            # R3-fix F-574：等值窗口与倒置一样不可达自写入面（表单/实体都拒
            # 等值），只可能来自手工改 storage——行为保持不变（两侧夹到同值），
            # 但必须落 WARNING 可审计，不再静默冻结推荐值
            _LOGGER.warning(
                "窗口上下限等值（min=max=%.1f），推荐值恒为该值", min_temp
            )
        elif min_temp > max_temp:
            _LOGGER.warning(
                "窗口上下限倒置（min=%.1f > max=%.1f），按交换后窗口计算",
                min_temp, max_temp,
            )
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
        """Listen for state changes of the 24h average inlet temperature entity."""
        entity = self.config[CONF_INLET_TEMP_SENSOR]

        @callback
        def _avg_changed(event):
            avg = self._parse_avg(event.data.get("new_state"))
            if avg is None or avg == self.last_avg_temp:
                return
            self.last_avg_temp = avg
            self._recalculate(avg)

        self._listeners.append(
            async_track_state_change_event(self.hass, entity, _avg_changed)
        )

        # R1 P2#2：启动即读一次当前 avg——重启后无需等首个 state_changed 才有
        # 推荐值（否则 auto_adjust 恢复时与参数热更新都静默停摆到下次均值变化）。
        # 此时 switch 平台尚未转发（__init__ 先建 optimizer 后 forward），switch
        # 的 RestoreEntity 恢复 auto_adjust=True 发生在平台加载时，晚于此处，
        # 不会出现"重启即下发"
        avg = self._parse_avg(self.hass.states.get(entity))
        if avg is not None:
            self.last_avg_temp = avg
            self._recalculate(avg)

    def _parse_avg(self, state) -> int | None:
        """把 avg 实体状态解析为有限整数；不可用/不可解析/非有限均落日志返回 None。

        血泪教训（v0.3.0 静默死亡 43 天）：忽略路径必须 INFO 以上落因，
        否则 avg 长期不可用时推荐值冻结却无任何日志可查。
        集成侧 round() 兜底整数化：不依赖 filter 的 precision 配置。
        """
        entity = self.config[CONF_INLET_TEMP_SENSOR]
        if state is None or state.state in (STATE_UNKNOWN, STATE_UNAVAILABLE, "none", ""):
            _LOGGER.info(
                "avg 实体 %s 状态为 %s，忽略本次变化（不重算）",
                entity, getattr(state, "state", None),
            )
            return None
        try:
            raw = float(state.state)
        except (TypeError, ValueError):
            _LOGGER.warning("avg 实体 %s 状态值 %r 不可解析为数值，忽略", entity, state.state)
            return None
        if not math.isfinite(raw):
            _LOGGER.warning("avg 实体 %s 值 %r 非有限数，忽略", entity, state.state)
            return None
        return round(raw)

    def stop(self) -> None:
        """Remove all listeners and cancel the pending apply task.

        同步 on_unload 回调可直调；幂等——二次调用空跑（R1 P2#3 setup
        失败回滚与正常卸载共用）。
        """
        for unsub in self._listeners:
            unsub()
        self._listeners.clear()
        if self._apply_task is not None:
            self._apply_task.cancel()

    def _spawn_apply(self, coro) -> None:
        """单飞创建下发任务（R1 P2#5）：先取消未完成的旧任务再挂新任务——
        去抖移除后 slider 连续写入不再多任务并发连发/乱序；任务异常落日志收口。
        """
        if self._apply_task is not None and not self._apply_task.done():
            self._apply_task.cancel()
        task = self.hass.async_create_task(coro)
        self._apply_task = task
        task.add_done_callback(self._apply_done)

    @callback
    def _apply_done(self, task) -> None:
        if self._apply_task is task:
            self._apply_task = None
        if task.cancelled():
            return
        if (exc := task.exception()) is not None:
            _LOGGER.error("下发任务异常终止: %s", exc)

    @callback
    def _recalculate(self, avg: int) -> None:
        """按新 avg 值重算推荐值并刷新实体；auto_adjust 开则比对下发。"""
        self.recommended_temp = self.calculate(avg)
        _LOGGER.info("24h 均值变化: avg=%d°C → recommended=%s°C", avg, self.recommended_temp)
        async_dispatcher_send(self.hass, self._signal)
        if self.auto_adjust and self.recommended_temp is not None:
            self._spawn_apply(self._apply_temperature())

    async def _apply_temperature(self) -> bool:
        """推荐值与热水器当前设定比对，不同才下发 set_temperature。

        比对口径：推荐值为整数；当前设定 round 到整数后比较（0.5 步进的
        设备值落在相邻整数视为相同，防"下发→设备回半度→再下发"循环）。
        热水器缺席或 temperature 不可读时 INFO 落因后跳过、不盲发
        （v0.3.0 静默死亡 43 天教训：跳过路径仅 debug 不可见——本批血泪
        教训最高优先，故此处按 INFO 执行，与计划书 §2.2 debug 口径的
        分歧已记录于续作门）。
        Returns True when a command was actually sent.
        """
        heater = self.config[CONF_WATER_HEATER]
        target = self.recommended_temp
        if target is None:
            return False
        # R1 P2#5：发送前复检总闸——排队期间被关掉的 任务不得继续下发
        # （血泪教训面：跳过路径 INFO 落因）
        if not self.auto_adjust:
            _LOGGER.info("自动调节已关，取消执行排队中的下发（推荐 %s°C）", target)
            return False
        heater_state = self.hass.states.get(heater)
        if heater_state is None:
            _LOGGER.info("热水器 %s 状态缺席，本次不下发，等下次均值变化重试", heater)
            return False
        # 按目标设备自身限值夹紧 (M2)
        try:
            lo = heater_state.attributes.get("min_temp")
            hi = heater_state.attributes.get("max_temp")
            if lo is not None:
                target = max(target, math.ceil(float(lo)))
            if hi is not None:
                target = min(target, math.floor(float(hi)))
        except (TypeError, ValueError, OverflowError):
            _LOGGER.info(
                "热水器 %s 的 min/max 属性不可解析（%r/%r），按集成侧窗口值 %d 下发",
                heater, heater_state.attributes.get("min_temp"),
                heater_state.attributes.get("max_temp"), target,
            )
        current = heater_state.attributes.get("temperature")
        if current is None:
            _LOGGER.info("热水器 %s 无当前设定温度属性，本次不下发", heater)
            return False
        try:
            current_val = float(current)
        except (TypeError, ValueError):
            _LOGGER.info("热水器 %s 当前设定温度 %r 不可解析，本次不下发", heater, current)
            return False
        if not math.isfinite(current_val):
            # R1 P3#10：round(nan)/round(inf) 会抛 ValueError/OverflowError
            _LOGGER.info("热水器 %s 当前设定温度 %r 非有限数，本次不下发", heater, current)
            return False
        if round(current_val) == target:
            _LOGGER.debug(
                "热水器当前设定 %.1f°C 与推荐值 %d°C 相同，不下发", current_val, target
            )
            return False
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
        """热应用可调参数（target_temp / hot_water_ratio / min_temp / max_temp），不重载条目。

        用最近一次有效 avg 值重算推荐值；自动调节开启时立即比对下发。
        并发治理：下发任务单飞（_spawn_apply），旧任务未完成即被新任务
        取代——slider 连续写入只发最后一个值，不会多任务并发连发。
        """
        self.config = {**self.entry.data, **self.entry.options}
        self.last_options = dict(self.entry.options)
        self.last_data = dict(self.entry.data)
        self.last_title = self.entry.title
        if self.last_avg_temp is not None:
            self.recommended_temp = self.calculate(self.last_avg_temp)
            _LOGGER.info(
                "参数已热更新: target=%s°C, ratio=%s, window=[%s, %s]°C → recommended=%s°C",
                self.config.get(CONF_TARGET_TEMP),
                self.config.get(CONF_HOT_WATER_RATIO),
                self.config.get(CONF_MIN_TEMP),
                self.config.get(CONF_MAX_TEMP),
                self.recommended_temp,
            )
        else:
            # R1 P2#2：无均值时不得静默跳过（血泪教训：跳过路径 INFO 落因）
            _LOGGER.info("尚无有效 24h 均值，参数已保存，待下次均值变化时生效")
        async_dispatcher_send(self.hass, self._signal)
        if self.auto_adjust and self.recommended_temp is not None:
            self._spawn_apply(self._apply_temperature())

    async def async_set_auto_adjust(self, enabled: bool):
        """Enable or disable auto-adjust."""
        self.auto_adjust = enabled
        if enabled and self.recommended_temp is not None:
            await self._apply_temperature()
        elif enabled:
            # R1 P2#2：开启但无推荐值时不得静默跳过（血泪教训面）
            _LOGGER.info("自动调节已开启，但当前无推荐值（尚无有效均值），暂不下发")
        async_dispatcher_send(self.hass, self._signal)
