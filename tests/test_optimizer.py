"""最小测试基线：calculate 纯函数 + avg 监听→重算→比对下发链路。

本机无 homeassistant 包：模块顶注入最小 HA 桩（签名已按 VM 容器
site-packages 实证：async_track_state_change_event(hass, entity_ids,
action) / async_dispatcher_send(hass, signal, *args) /
water_heater.set_temperature 的 temperature 字段 required）。
"""
import asyncio
import importlib
import sys
import types
from pathlib import Path

import pytest


def _install_ha_stubs() -> None:
    """注入 optimizer/__init__ import 面所需的最小 HA 模块桩。"""
    if "homeassistant" in sys.modules:
        return

    ha = types.ModuleType("homeassistant")
    ha_const = types.ModuleType("homeassistant.const")
    ha_const.STATE_UNAVAILABLE = "unavailable"
    ha_const.STATE_UNKNOWN = "unknown"

    class _Platform:
        SENSOR = "sensor"
        SWITCH = "switch"
        NUMBER = "number"

    ha_const.Platform = _Platform

    ha_core = types.ModuleType("homeassistant.core")

    class _HomeAssistant:
        pass

    def _callback(fn):
        return fn

    ha_core.HomeAssistant = _HomeAssistant
    ha_core.callback = _callback
    ha_core.Event = object

    ha_exc = types.ModuleType("homeassistant.exceptions")

    class _HomeAssistantError(Exception):
        # 签名对齐 HA 2026.1.3 exceptions.py:39-54（R3-fix F-576 翻译异常）
        def __init__(
            self,
            *args,
            translation_domain=None,
            translation_key=None,
            translation_placeholders=None,
        ):
            super().__init__(*args)
            self.translation_domain = translation_domain
            self.translation_key = translation_key
            self.translation_placeholders = translation_placeholders

    ha_exc.HomeAssistantError = _HomeAssistantError

    ha_ce = types.ModuleType("homeassistant.config_entries")

    class _ConfigEntry:
        pass

    class _ConfigFlow:
        def __init_subclass__(cls, domain=None, **kwargs):
            super().__init_subclass__(**kwargs)

    class _OptionsFlow:
        pass

    ha_ce.ConfigEntry = _ConfigEntry
    ha_ce.ConfigFlow = _ConfigFlow
    ha_ce.OptionsFlow = _OptionsFlow

    ha_helpers = types.ModuleType("homeassistant.helpers")
    ha_disp = types.ModuleType("homeassistant.helpers.dispatcher")

    def _async_dispatcher_send(hass, signal, *args):
        hass.signals.append(signal)

    def _async_dispatcher_connect(hass, signal, target):
        return lambda: None

    ha_disp.async_dispatcher_send = _async_dispatcher_send
    ha_disp.async_dispatcher_connect = _async_dispatcher_connect

    ha_event = types.ModuleType("homeassistant.helpers.event")

    def _async_track_state_change_event(hass, entity_ids, action):
        hass.tracked.append((entity_ids, action))
        return lambda: None

    ha_event.async_track_state_change_event = _async_track_state_change_event

    ha_typing = types.ModuleType("homeassistant.helpers.typing")
    ha_typing.ConfigType = dict

    ha_helpers.dispatcher = ha_disp
    ha_helpers.event = ha_event
    ha_helpers.typing = ha_typing

    # number.py 的 import 面（FX-UX-126 步7 参数原生化）
    ha_number = types.ModuleType("homeassistant.components.number")

    class _NumberEntity:
        _attr_unique_id: str | None = None
        _attr_native_min_value: float | None = None
        _attr_native_max_value: float | None = None
        _attr_native_step: float | None = None
        _attr_mode = None

        @property
        def unique_id(self):
            return self._attr_unique_id

        @property
        def native_min_value(self):
            return self._attr_native_min_value

        @property
        def native_max_value(self):
            return self._attr_native_max_value

        @property
        def native_step(self):
            return self._attr_native_step

        @property
        def mode(self):
            return self._attr_mode

        def async_write_ha_state(self):
            pass  # 桩：生产路径为同步刷状态，测试只需不炸

    class _NumberMode:
        AUTO = "auto"
        BOX = "box"
        SLIDER = "slider"

    ha_number.NumberEntity = _NumberEntity
    ha_number.NumberMode = _NumberMode

    ha_entity = types.ModuleType("homeassistant.helpers.entity")

    class _DeviceInfo:
        def __init__(self, **kwargs):
            self.kwargs = dict(kwargs)

    ha_entity.DeviceInfo = _DeviceInfo

    ha_platform = types.ModuleType("homeassistant.helpers.entity_platform")
    ha_platform.AddEntitiesCallback = object

    ha_helpers.entity = ha_entity
    ha_helpers.entity_platform = ha_platform

    for name, mod in {
        "homeassistant": ha,
        "homeassistant.const": ha_const,
        "homeassistant.core": ha_core,
        "homeassistant.exceptions": ha_exc,
        "homeassistant.config_entries": ha_ce,
        "homeassistant.helpers": ha_helpers,
        "homeassistant.helpers.dispatcher": ha_disp,
        "homeassistant.helpers.event": ha_event,
        "homeassistant.helpers.typing": ha_typing,
        "homeassistant.components.number": ha_number,
        "homeassistant.helpers.entity": ha_entity,
        "homeassistant.helpers.entity_platform": ha_platform,
    }.items():
        sys.modules[name] = mod


_install_ha_stubs()
sys.path.insert(
    0, str(Path(__file__).resolve().parents[1] / "custom_components")
)

optimizer_mod = importlib.import_module("water_heater_optimizer.optimizer")
number_mod = importlib.import_module("water_heater_optimizer.number")
WaterHeaterOptimizer = optimizer_mod.WaterHeaterOptimizer


class FakeState:
    def __init__(self, state, attributes=None):
        self.state = state
        self.attributes = attributes or {}


class FakeStates:
    def __init__(self, states=None):
        self._states = states or {}

    def get(self, entity_id):
        return self._states.get(entity_id)


class FakeServices:
    def __init__(self):
        self.calls = []
        self.fail = False

    async def async_call(self, domain, service, data, blocking=False):
        self.calls.append((domain, service, data))
        if self.fail:
            from homeassistant.exceptions import HomeAssistantError

            raise HomeAssistantError("boom")


class FakeHass:
    def __init__(self, states=None):
        self.states = FakeStates(states)
        self.services = FakeServices()
        self.signals = []
        self.tracked = []
        self.tasks = []
        self.data = {}

    def async_create_task(self, coro):
        task = asyncio.get_running_loop().create_task(coro)
        self.tasks.append(task)
        return task


class FakeConfigEntries:
    """async_update_entry/async_schedule_reload 最小桩（number 写入路径用）。"""

    def __init__(self):
        self.updates = []
        self.reloads = []

    def async_update_entry(self, entry, **kwargs):
        if "options" in kwargs:
            entry.options = dict(kwargs["options"])
        self.updates.append((entry.entry_id, sorted(kwargs)))
        return True

    def async_schedule_reload(self, entry_id):
        self.reloads.append(entry_id)


def make_optimizer_entry_data():
    return {
        "water_heater": "water_heater.test",
        "inlet_temp_sensor": "sensor.avg_inlet",
        "target_temp": 37,
        "hot_water_ratio": 0.7,
        "min_temp": 40,
        "max_temp": 50,
    }


def make_optimizer(states=None):
    entry = types.SimpleNamespace(
        data=make_optimizer_entry_data(),
        options={},
        title="Optimizer test",
        entry_id="test_entry",
    )
    hass = FakeHass(states)
    return hass, WaterHeaterOptimizer(hass, entry)


def fire_avg(hass, value):
    """向已注册的监听器投一条 avg 状态事件。"""
    _entity, action = hass.tracked[0]
    action(
        types.SimpleNamespace(
            data={"old_state": None, "new_state": FakeState(value)}
        )
    )


async def drain(hass):
    """等所有 spawn 的下发任务跑完（含被单飞取消的任务）。"""
    if hass.tasks:
        await asyncio.gather(*hass.tasks, return_exceptions=True)


# --- calculate 纯函数 ---


def test_calculate_basic():
    _, opt = make_optimizer()
    # 20 + (37-20)/0.7 = 44.29 → 44（窗口内无夹紧）
    assert opt.calculate(20) == 44


def test_calculate_clamps_to_min():
    _, opt = make_optimizer()
    # 35 + 2/0.7 = 37.86 → 夹到 min 40
    assert opt.calculate(35) == 40


def test_calculate_clamps_to_max():
    _, opt = make_optimizer()
    # 5 + 32/0.7 = 50.71 → 夹到 max 50
    assert opt.calculate(5) == 50


def test_calculate_invalid_ratio():
    _, opt = make_optimizer()
    opt.config["hot_water_ratio"] = 0
    assert opt.calculate(20) is None
    opt.config["hot_water_ratio"] = "abc"
    assert opt.calculate(20) is None


def test_calculate_none_tap():
    _, opt = make_optimizer()
    assert opt.calculate(None) is None


def test_calculate_swaps_min_max():
    _, opt = make_optimizer()
    opt.config["min_temp"] = 50
    opt.config["max_temp"] = 40
    # 交换后窗口 [40,50]：37.86 → 夹到 40（不交换会夹到 50）
    assert opt.calculate(35) == 40


# --- avg 监听→重算→比对下发 ---


def test_avg_integer_change_recalculates():
    async def scenario():
        hass, opt = make_optimizer()
        await opt.async_setup()
        assert len(opt._listeners) == 1

        fire_avg(hass, "20")
        assert opt.last_avg_temp == 20
        assert opt.recommended_temp == 44
        assert hass.signals  # dispatcher 已刷实体

        # 同整数值（20.3 → round 20）不重算、不再刷
        n_signals = len(hass.signals)
        fire_avg(hass, "20.3")
        assert opt.last_avg_temp == 20
        assert len(hass.signals) == n_signals

        # 新整数 → 重算
        fire_avg(hass, "21")
        assert opt.recommended_temp == opt.calculate(21)

    asyncio.run(scenario())


def test_avg_unavailable_unknown_garbage_ignored():
    async def scenario():
        hass, opt = make_optimizer()
        await opt.async_setup()
        fire_avg(hass, "20")
        n_signals = len(hass.signals)
        for bad in ("unavailable", "unknown", "none", "", "abc", "nan", "inf"):
            fire_avg(hass, bad)
        assert opt.last_avg_temp == 20
        assert opt.recommended_temp == 44
        assert len(hass.signals) == n_signals

    asyncio.run(scenario())


def test_no_dispatch_when_switch_off():
    async def scenario():
        heater = FakeState(
            "heat_pump", {"temperature": 42, "min_temp": 35, "max_temp": 75}
        )
        hass, opt = make_optimizer(states={"water_heater.test": heater})
        await opt.async_setup()
        opt.auto_adjust = False
        fire_avg(hass, "20")  # 推荐 44 ≠ 42，但总闸关
        await drain(hass)
        assert hass.services.calls == []

    asyncio.run(scenario())


def test_dispatches_when_switch_on_and_differs():
    async def scenario():
        heater = FakeState(
            "heat_pump", {"temperature": 42, "min_temp": 35, "max_temp": 75}
        )
        hass, opt = make_optimizer(states={"water_heater.test": heater})
        await opt.async_setup()
        opt.auto_adjust = True
        fire_avg(hass, "20")  # 推荐 44 ≠ 当前 42 → 下发 44
        await drain(hass)
        assert len(hass.services.calls) == 1
        domain, service, data = hass.services.calls[0]
        assert (domain, service) == ("water_heater", "set_temperature")
        assert data == {"entity_id": "water_heater.test", "temperature": 44}
        assert opt.applied_temp == 44

    asyncio.run(scenario())


def test_no_dispatch_when_same_setting():
    async def scenario():
        heater = FakeState(
            "heat_pump", {"temperature": 44, "min_temp": 35, "max_temp": 75}
        )
        hass, opt = make_optimizer(states={"water_heater.test": heater})
        await opt.async_setup()
        opt.auto_adjust = True
        fire_avg(hass, "20")  # 推荐 44 == 当前 44 → 相同不动
        await drain(hass)
        assert hass.services.calls == []

    asyncio.run(scenario())


def test_half_degree_setting_treated_as_same():
    async def scenario():
        heater = FakeState(
            "heat_pump", {"temperature": 44.5, "min_temp": 35, "max_temp": 75}
        )
        hass, opt = make_optimizer(states={"water_heater.test": heater})
        await opt.async_setup()
        opt.auto_adjust = True
        fire_avg(hass, "20")  # 推荐 44；round(44.5)=44 → 视为相同不下发
        await drain(hass)
        assert hass.services.calls == []

    asyncio.run(scenario())


def test_no_blind_send_when_heater_missing():
    async def scenario():
        hass, opt = make_optimizer(states={})  # 热水器缺席
        await opt.async_setup()
        opt.auto_adjust = True
        fire_avg(hass, "20")
        await drain(hass)
        assert hass.services.calls == []

    asyncio.run(scenario())


def test_heater_missing_logs_info(caplog):
    async def scenario():
        hass, opt = make_optimizer(states={})
        await opt.async_setup()
        opt.auto_adjust = True
        with caplog.at_level("INFO"):
            fire_avg(hass, "20")
            await drain(hass)
        assert "状态缺席" in caplog.text

    asyncio.run(scenario())


def test_no_send_when_temperature_unparseable():
    async def scenario():
        heater = FakeState(
            "heat_pump", {"temperature": "n/a", "min_temp": 35, "max_temp": 75}
        )
        hass, opt = make_optimizer(states={"water_heater.test": heater})
        await opt.async_setup()
        opt.auto_adjust = True
        fire_avg(hass, "20")
        await drain(hass)
        assert hass.services.calls == []

    asyncio.run(scenario())


def test_dispatch_clamped_to_device_limits():
    async def scenario():
        heater = FakeState(
            "heat_pump", {"temperature": 42, "min_temp": 46, "max_temp": 75}
        )
        hass, opt = make_optimizer(states={"water_heater.test": heater})
        await opt.async_setup()
        opt.auto_adjust = True
        fire_avg(hass, "20")  # 推荐 44，设备 min 46 → 下发 46
        await drain(hass)
        assert hass.services.calls[0][2]["temperature"] == 46

    asyncio.run(scenario())


def test_switch_on_applies_immediately():
    async def scenario():
        heater = FakeState(
            "heat_pump", {"temperature": 42, "min_temp": 35, "max_temp": 75}
        )
        hass, opt = make_optimizer(states={"water_heater.test": heater})
        await opt.async_setup()
        fire_avg(hass, "20")
        assert hass.services.calls == []  # 总闸还是关的
        await opt.async_set_auto_adjust(True)
        assert len(hass.services.calls) == 1
        assert hass.services.calls[0][2]["temperature"] == 44

    asyncio.run(scenario())


def test_unload_clears_listeners():
    async def scenario():
        _hass, opt = make_optimizer()
        await opt.async_setup()
        assert len(opt._listeners) == 1
        opt.stop()
        assert opt._listeners == []
        opt.stop()  # 幂等：二次调用空跑（R1 P2#3）

    asyncio.run(scenario())


# --- R1 修复轮新增：启动读取/热应用/单飞/总闸/回滚/有限性 ---


def test_setup_reads_current_avg():
    async def scenario():
        # R1 P2#2：启动即读当前 avg——重启后不等首个 state_changed
        hass, opt = make_optimizer(
            states={"sensor.avg_inlet": FakeState("20")}
        )
        await opt.async_setup()
        assert opt.last_avg_temp == 20
        assert opt.recommended_temp == 44
        assert hass.signals  # 实体已刷
        # 总闸未开（switch 平台尚未恢复），不下发
        await drain(hass)
        assert hass.services.calls == []

    asyncio.run(scenario())


def test_setup_avg_unavailable_logs_info(caplog):
    async def scenario():
        # R1 P2#2：启动时 avg 不可用也不得静默（血泪教训面）
        _hass, opt = make_optimizer(
            states={"sensor.avg_inlet": FakeState("unavailable")}
        )
        with caplog.at_level("INFO"):
            await opt.async_setup()
        assert opt.last_avg_temp is None
        assert opt.recommended_temp is None
        assert "忽略" in caplog.text

    asyncio.run(scenario())


def test_apply_live_config_recalculates_and_dispatches():
    async def scenario():
        # R1 P3#7：参数热更新 → 用最近 avg 重算 → 比对下发
        heater = FakeState(
            "heat_pump", {"temperature": 42, "min_temp": 35, "max_temp": 75}
        )
        hass, opt = make_optimizer(states={"water_heater.test": heater})
        await opt.async_setup()
        fire_avg(hass, "20")
        await drain(hass)
        opt.auto_adjust = True
        # target 37→39：20 + (39-20)/0.7 = 47.14 → 47
        opt.entry.options = {**opt.entry.options, "target_temp": 39}
        opt.apply_live_config()
        await drain(hass)
        assert opt.recommended_temp == 47
        assert len(hass.services.calls) == 1
        assert hass.services.calls[0][2]["temperature"] == 47

    asyncio.run(scenario())


def test_apply_live_config_without_avg_logs_info(caplog):
    async def scenario():
        # R1 P2#2/P3#7：无均值时热应用不得静默跳过
        hass, opt = make_optimizer()
        await opt.async_setup()
        with caplog.at_level("INFO"):
            opt.apply_live_config()
        await drain(hass)
        assert opt.recommended_temp is None
        assert "尚无有效" in caplog.text
        assert hass.services.calls == []

    asyncio.run(scenario())


def test_consecutive_applies_single_flight():
    async def scenario():
        # R1 P2#5：连续两次热应用（slider 拖动态势）——第一个任务被第二个
        # 取代，只发最后一个值
        heater = FakeState(
            "heat_pump", {"temperature": 42, "min_temp": 35, "max_temp": 75}
        )
        hass, opt = make_optimizer(states={"water_heater.test": heater})
        await opt.async_setup()
        fire_avg(hass, "20")
        await drain(hass)
        opt.auto_adjust = True
        opt.entry.options = {**opt.entry.options, "target_temp": 39}
        opt.apply_live_config()  # 推荐 47，任务排队未跑
        opt.entry.options = {**opt.entry.options, "target_temp": 40}
        opt.apply_live_config()  # 推荐 49，取代上一个
        await drain(hass)
        assert len(hass.services.calls) == 1
        assert hass.services.calls[0][2]["temperature"] == 49

    asyncio.run(scenario())


def test_queued_apply_aborts_when_switch_off(caplog):
    async def scenario():
        # R1 P2#5：总闸关闭后排队任务不得继续下发（发送前复检）
        heater = FakeState(
            "heat_pump", {"temperature": 42, "min_temp": 35, "max_temp": 75}
        )
        hass, opt = make_optimizer(states={"water_heater.test": heater})
        await opt.async_setup()
        fire_avg(hass, "20")
        opt.auto_adjust = True
        opt.entry.options = {**opt.entry.options, "target_temp": 39}
        opt.apply_live_config()  # 任务排队
        await opt.async_set_auto_adjust(False)  # 总闸关闭
        with caplog.at_level("INFO"):
            await drain(hass)
        assert hass.services.calls == []
        assert "自动调节已关" in caplog.text

    asyncio.run(scenario())


def test_switch_on_without_recommendation_logs_info(caplog):
    async def scenario():
        # R1 P2#2：总闸开但无推荐值时不得静默跳过
        hass, opt = make_optimizer()
        await opt.async_setup()
        with caplog.at_level("INFO"):
            await opt.async_set_auto_adjust(True)
        assert "暂不下发" in caplog.text
        assert hass.services.calls == []

    asyncio.run(scenario())


def test_apply_service_error_logged_not_applied(caplog):
    async def scenario():
        # R1 P3#7：服务调用失败 → error 落日志、applied_temp 不更新
        heater = FakeState(
            "heat_pump", {"temperature": 42, "min_temp": 35, "max_temp": 75}
        )
        hass, opt = make_optimizer(states={"water_heater.test": heater})
        hass.services.fail = True
        await opt.async_setup()
        opt.auto_adjust = True
        with caplog.at_level("ERROR"):
            fire_avg(hass, "20")
            await drain(hass)
        assert len(hass.services.calls) == 1  # 尝试过调用
        assert opt.applied_temp is None
        assert "下发设定温度" in caplog.text

    asyncio.run(scenario())


def test_calculate_nonfinite_rejected():
    _, opt = make_optimizer()
    # R1 P3#10：NaN/inf 配置一律拒绝，不再混过守卫抛到回调里
    for key in ("target_temp", "hot_water_ratio", "min_temp", "max_temp"):
        backup = opt.config[key]
        opt.config[key] = float("nan")
        assert opt.calculate(20) is None
        opt.config[key] = float("inf")
        assert opt.calculate(20) is None
        opt.config[key] = backup


def test_apply_skips_nonfinite_current():
    async def scenario():
        # R1 P3#10：设备当前设定为 NaN 时跳过不炸（round(nan) 抛 ValueError）
        heater = FakeState(
            "heat_pump",
            {"temperature": float("nan"), "min_temp": 35, "max_temp": 75},
        )
        hass, opt = make_optimizer(states={"water_heater.test": heater})
        await opt.async_setup()
        opt.auto_adjust = True
        fire_avg(hass, "20")
        await drain(hass)
        assert hass.services.calls == []

    asyncio.run(scenario())


def test_setup_entry_rollback_on_forward_error():
    async def scenario():
        # R1 P2#3：setup 中途抛错后 on_unload 链回滚——hass.data 与 listener 清
        # （原注入点=0.5.0 已下线的壳信息页 setup 抛错，现改用平台转发抛错）
        import water_heater_optimizer as wha

        on_unload = []
        entry = types.SimpleNamespace(
            data=dict(make_optimizer_entry_data()),
            options={},
            title="Optimizer test",
            entry_id="test_entry",
            async_on_unload=on_unload.append,
            add_update_listener=lambda fn: (lambda: None),
        )
        hass = FakeHass()

        async def _fail_forward(entry_, platforms):
            raise RuntimeError("forward boom")

        hass.config_entries = types.SimpleNamespace(
            async_forward_entry_setups=_fail_forward
        )

        try:
            await wha.async_setup_entry(hass, entry)
        except RuntimeError:
            pass

        # 抛错现场：optimizer 与 listener 仍在（HA 尚未跑 on_unload 链）
        opt = hass.data["water_heater_optimizer"]["test_entry"]
        assert len(opt._listeners) == 1
        # 模拟 HA 的 setup 失败处理：执行 on_unload 链（_cleanup 在其中）
        for fn in on_unload:
            fn()
        assert opt._listeners == []
        assert "test_entry" not in hass.data.get("water_heater_optimizer", {})

    asyncio.run(scenario())


# --- FX-UX-126 步7：min/max 参数原生化 ---


def _register_optimizer(hass, opt):
    """按 async_setup_entry 的真实形态把 optimizer 挂进 hass.data（listener 依赖）。"""
    hass.data.setdefault("water_heater_optimizer", {})[opt.entry.entry_id] = opt


def test_min_max_number_entity_ranges():
    _hass, opt = make_optimizer()
    mn = number_mod.MinTempNumber(opt, opt.entry)
    mx = number_mod.MaxTempNumber(opt, opt.entry)
    # 值域与 config_flow 选择器一致（min 30-60 / max 30-70，step 1，BOX）
    assert (mn.native_min_value, mn.native_max_value, mn.native_step) == (
        30.0, 60.0, 1.0,
    )
    assert (mx.native_min_value, mx.native_max_value, mx.native_step) == (
        30.0, 70.0, 1.0,
    )
    assert mn.mode == number_mod.NumberMode.BOX
    assert mx.mode == number_mod.NumberMode.BOX
    # unique_id 命名照既有族（entry_id_后缀）
    assert mn.unique_id == "test_entry_min_temp"
    assert mx.unique_id == "test_entry_max_temp"
    # native_value 读 config（options 优先，data 兜底）
    assert mn.native_value == 40
    assert mx.native_value == 50


def test_min_max_number_set_value_snaps_clamps_persists():
    async def scenario():
        hass, opt = make_optimizer()
        hass.config_entries = FakeConfigEntries()
        mn = number_mod.MinTempNumber(opt, opt.entry)
        mx = number_mod.MaxTempNumber(opt, opt.entry)
        await mn.async_set_native_value(25)  # 低于下限 → 吸附夹到 30
        assert opt.entry.options["min_temp"] == 30
        await mn.async_set_native_value(45)  # 窗口内原样落盘
        assert opt.entry.options["min_temp"] == 45
        await mx.async_set_native_value(75)  # 高于上限 → 吸附夹到 70
        assert opt.entry.options["max_temp"] == 70
        # 三次写入都走 set_live_config → async_update_entry（entry.options 持久化路径）
        assert len(hass.config_entries.updates) == 3
        assert hass.config_entries.reloads == []

    asyncio.run(scenario())


def test_min_max_live_keys_hot_apply_without_reload():
    async def scenario():
        # FX-UX-126 步7：min/max 加入 _LIVE_KEYS——仅这两键变化走热应用
        # （重算消费 calculate 的窗口夹紧），不触发整条目重载
        import water_heater_optimizer as wha

        heater = FakeState(
            "heat_pump", {"temperature": 42, "min_temp": 35, "max_temp": 75}
        )
        hass, opt = make_optimizer(states={"water_heater.test": heater})
        await opt.async_setup()
        fire_avg(hass, "20")  # 推荐 44（窗口 40-50）
        _register_optimizer(hass, opt)
        hass.config_entries = FakeConfigEntries()

        mn = number_mod.MinTempNumber(opt, opt.entry)
        await mn.async_set_native_value(45)  # options: min_temp 40→45
        await wha._async_update_listener(hass, opt.entry)  # 模拟 HA update listener
        assert hass.config_entries.reloads == []  # 未重载
        assert opt.recommended_temp == 45  # 44 被新窗口下限夹到 45

        fire_avg(hass, "5")  # 均值变化重算：5+32/0.7=50.7→51，夹到窗口 [45,50] → 50
        assert opt.recommended_temp == 50

        mx = number_mod.MaxTempNumber(opt, opt.entry)
        await mx.async_set_native_value(48)  # options: max_temp 50→48
        await wha._async_update_listener(hass, opt.entry)
        assert hass.config_entries.reloads == []
        assert opt.recommended_temp == 48  # 51 被新窗口上限夹到 48

    asyncio.run(scenario())


def test_structural_key_change_still_reloads():
    async def scenario():
        # 结构性键（water_heater）变化不因 _LIVE_KEYS 扩容而漏判——仍走重载
        import water_heater_optimizer as wha

        hass, opt = make_optimizer()
        await opt.async_setup()
        _register_optimizer(hass, opt)
        hass.config_entries = FakeConfigEntries()
        opt.entry.options = {
            **opt.entry.options,
            "water_heater": "water_heater.other",
        }
        await wha._async_update_listener(hass, opt.entry)
        assert hass.config_entries.reloads == [opt.entry.entry_id]

    asyncio.run(scenario())


# --- FX-UX-126 R1-fix：P2#1 窗口交叉校验 + 交换分支可见性 ---


def test_min_max_number_cross_constraint_rejects_inverted_window():
    async def scenario():
        # R1 P2#1：number 写入前做 min<max 交叉校验，与表单 invalid_range
        # 语义对齐（等值也拒）；拦截时不落 options、不触发 set_live_config
        from homeassistant.exceptions import HomeAssistantError

        hass, opt = make_optimizer()
        hass.config_entries = FakeConfigEntries()
        mn = number_mod.MinTempNumber(opt, opt.entry)
        mx = number_mod.MaxTempNumber(opt, opt.entry)

        with pytest.raises(HomeAssistantError):
            await mn.async_set_native_value(60)  # 60 >= 当前 max 50 → 拒
        assert "min_temp" not in opt.entry.options
        assert hass.config_entries.updates == []

        with pytest.raises(HomeAssistantError):
            await mx.async_set_native_value(30)  # 30 <= 当前 min 40 → 拒
        assert "max_temp" not in opt.entry.options

        with pytest.raises(HomeAssistantError):
            await mn.async_set_native_value(50)  # 50 == 当前 max 50 → 等值拒

        await mn.async_set_native_value(45)  # 45 < 50 → 合法放行
        assert opt.entry.options["min_temp"] == 45
        with pytest.raises(HomeAssistantError):
            await mx.async_set_native_value(45)  # 45 <= 当前 min 45 → 等值拒

    asyncio.run(scenario())


def test_calculate_swapped_window_logs_warning(caplog):
    # R1 P2#1②：手工改 storage 造成窗口倒置时，交换分支不再无声
    _, opt = make_optimizer()
    opt.config["min_temp"] = 60
    opt.config["max_temp"] = 50
    with caplog.at_level("WARNING"):
        assert opt.calculate(20) == 50  # 交换后 [50,60]：44.29 → 夹到下限 50
    assert "倒置" in caplog.text


# --- wh-dehub-126 R3-fix：F-574 等值窗口 / F-575 NaN sibling /
# --- F-576 翻译异常 / F-577 number 接线钉 / F-647 重载·启动追平


def test_calculate_equal_window_logs_warning(caplog):
    # F-574：等值窗口（min==max，手工改 storage 可达）不再静默——与倒置
    # 分支同款 WARNING，行为不变（两侧夹到同值）
    _, opt = make_optimizer()
    opt.config["min_temp"] = 50
    opt.config["max_temp"] = 50
    with caplog.at_level("WARNING"):
        assert opt.calculate(20) == 50
    assert "等值" in caplog.text


def test_number_cross_constraint_nan_sibling_warns_and_allows(caplog):
    async def scenario():
        # F-575：sibling 为 NaN 时 IEEE 比较恒 False 曾静默绕过两个 raise——
        # 现在落 WARNING 后放行（坏值由 calculate 的 isfinite 守卫兜底响）
        hass, opt = make_optimizer()
        hass.config_entries = FakeConfigEntries()
        opt.entry.options["max_temp"] = float("nan")
        mn = number_mod.MinTempNumber(opt, opt.entry)
        with caplog.at_level("WARNING"):
            await mn.async_set_native_value(60)  # 60 >= NaN 恒 False → 走放行
        assert opt.entry.options["min_temp"] == 60
        assert "非有限" in caplog.text
        assert len(hass.config_entries.updates) == 1  # 放行且落盘

    asyncio.run(scenario())


def test_number_cross_constraint_raises_translated_error():
    async def scenario():
        # F-576：拒绝路径的 HomeAssistantError 走翻译体系（不再中文硬编码）
        from homeassistant.exceptions import HomeAssistantError

        hass, opt = make_optimizer()
        hass.config_entries = FakeConfigEntries()
        mn = number_mod.MinTempNumber(opt, opt.entry)
        mx = number_mod.MaxTempNumber(opt, opt.entry)
        with pytest.raises(HomeAssistantError) as exc_min:
            await mn.async_set_native_value(60)
        assert exc_min.value.translation_domain == "water_heater_optimizer"
        assert exc_min.value.translation_key == "invalid_window"
        assert exc_min.value.translation_placeholders == {
            "min_temp": "60",
            "max_temp": "50",
        }
        with pytest.raises(HomeAssistantError) as exc_max:
            await mx.async_set_native_value(30)
        assert exc_max.value.translation_key == "invalid_window"
        # max 写入方向同一不变量：占位符仍陈述 min<max（sibling 在前）
        assert exc_max.value.translation_placeholders == {
            "min_temp": "40",
            "max_temp": "30",
        }

    asyncio.run(scenario())


def test_number_platform_setup_registers_all_entities():
    async def scenario():
        # F-577：接线钉——async_setup_entry 必须注册全部四类实体（此前所有
        # 钉都直实例化，实体清单漂移不会变红）
        hass, opt = make_optimizer()
        _register_optimizer(hass, opt)
        added = []
        # AddEntitiesCallback 语义=收实体列表（async_add_entities([...]) 一次
        # 传入整表），用 extend 展平
        await number_mod.async_setup_entry(hass, opt.entry, added.extend)
        assert [type(e).__name__ for e in added] == [
            "TargetTempNumber",
            "HotWaterRatioNumber",
            "MinTempNumber",
            "MaxTempNumber",
        ]

    asyncio.run(scenario())


def _make_full_entry(data_overrides=None):
    """带 on_unload/listener 桩的完整 entry（async_setup_entry 全路径用）。"""
    return types.SimpleNamespace(
        data=dict(make_optimizer_entry_data(), **(data_overrides or {})),
        options={},
        title="Optimizer test",
        entry_id="test_entry",
        async_on_unload=lambda fn: None,
        add_update_listener=lambda fn: (lambda: None),
    )


async def _setup_entry_simulating_reload(hass, entry, restored_on=True):
    """跑 async_setup_entry 全路径，forward 桩模拟平台加载时序。

    时序依据（HA 2026.1.3 wheel 实证）：async_forward_entry_setups 返回前
    各实体 async_added_to_hass 已跑完（entity_platform.py:1010 →
    entity.py:1378），switch 的 RestoreEntity 在其中把 auto_adjust 恢复
    到 optimizer——桩在该点写入 restored_on 复刻真机顺序。
    """
    import water_heater_optimizer as wha

    async def _forward(entry_, platforms):
        hass.data["water_heater_optimizer"][entry_.entry_id].auto_adjust = (
            restored_on
        )

    hass.config_entries = types.SimpleNamespace(async_forward_entry_setups=_forward)
    return await wha.async_setup_entry(hass, entry)


def test_setup_entry_catches_up_after_structural_reload():
    async def scenario():
        # F-647 场景钉（用户 2026-11-16 实测形态）：结构性键（inlet 均值源）
        # 变更 → 条目重载 → rec=46（avg22+target39+ratio0.7，窗口[40,48]）
        # 但新均值恒定使监听器永不触发 → setup 完成后必须追平一次下发
        heater = FakeState(
            "heat_pump", {"temperature": 50, "min_temp": 35, "max_temp": 75}
        )
        entry = _make_full_entry({
            "inlet_temp_sensor": "sensor.avg_new",
            "target_temp": 39,
            "min_temp": 40,
            "max_temp": 48,
        })
        hass = FakeHass(states={
            "sensor.avg_new": FakeState("22"),
            "water_heater.test": heater,
        })
        assert await _setup_entry_simulating_reload(hass, entry) is True
        opt = hass.data["water_heater_optimizer"]["test_entry"]
        assert opt.recommended_temp == 46  # 22+(39-22)/0.7=46.29 → 46
        await drain(hass)
        assert len(hass.services.calls) == 1  # 设备 50 ≠ rec 46 → 追平下发
        assert hass.services.calls[0][2] == {
            "entity_id": "water_heater.test",
            "temperature": 46,
        }

    asyncio.run(scenario())


def test_setup_entry_catchup_no_send_when_same_setting():
    async def scenario():
        # F-647 判别钉②：rec == 设备设定 → 不下发不误报
        heater = FakeState(
            "heat_pump", {"temperature": 44, "min_temp": 35, "max_temp": 75}
        )
        hass = FakeHass(states={
            "sensor.avg_inlet": FakeState("20"),
            "water_heater.test": heater,
        })
        assert await _setup_entry_simulating_reload(hass, _make_full_entry()) is True
        await drain(hass)
        assert hass.services.calls == []

    asyncio.run(scenario())


def test_setup_entry_catchup_skips_when_heater_missing(caplog):
    async def scenario():
        # F-647 判别钉③：设备缺席 → INFO 跳过，不炸 setup
        hass = FakeHass(states={"sensor.avg_inlet": FakeState("20")})
        with caplog.at_level("INFO"):
            assert await _setup_entry_simulating_reload(
                hass, _make_full_entry()
            ) is True
            # 追平任务 setup 返回后才执行（async_create_task），drain 须留在
            # 捕获窗口内，否则跳过 INFO 落在 at_level 块外不被捕获
            await drain(hass)
        assert hass.services.calls == []
        assert "状态缺席" in caplog.text

    asyncio.run(scenario())


def test_setup_entry_no_catchup_when_switch_restored_off():
    async def scenario():
        # F-647 判别钉④：总闸恢复为 off → 无追平（guard 只认 on）
        heater = FakeState(
            "heat_pump", {"temperature": 42, "min_temp": 35, "max_temp": 75}
        )
        hass = FakeHass(states={
            "sensor.avg_inlet": FakeState("20"),
            "water_heater.test": heater,
        })
        assert await _setup_entry_simulating_reload(
            hass, _make_full_entry(), restored_on=False
        ) is True
        await drain(hass)
        assert hass.services.calls == []

    asyncio.run(scenario())
