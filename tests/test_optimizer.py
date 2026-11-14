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


def _install_ha_stubs() -> None:
    """注入 optimizer/__init__ import 面所需的最小 HA 模块桩。"""
    if "homeassistant" in sys.modules:
        return

    ha = types.ModuleType("homeassistant")
    ha_const = types.ModuleType("homeassistant.const")
    ha_const.STATE_UNAVAILABLE = "unavailable"
    ha_const.STATE_UNKNOWN = "unknown"
    ha_const.EVENT_HOMEASSISTANT_STARTED = "homeassistant_started"

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
        pass

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

    # web.py 的 import 面（包 __init__ 会 import web）
    aiohttp_mod = types.ModuleType("aiohttp")
    aiohttp_web = types.ModuleType("aiohttp.web")

    class _Request:
        pass

    class _Response:
        pass

    aiohttp_web.Request = _Request
    aiohttp_web.Response = _Response
    aiohttp_mod.web = aiohttp_web

    ha_components = types.ModuleType("homeassistant.components")
    ha_http = types.ModuleType("homeassistant.components.http")

    class _HomeAssistantView:
        url = ""
        name = ""
        requires_auth = True

        @staticmethod
        def json(data):
            return data

    def _require_admin(fn):
        return fn

    class _StaticPathConfig:
        def __init__(self, *args, **kwargs):
            pass

    ha_http.HomeAssistantView = _HomeAssistantView
    ha_http.require_admin = _require_admin
    ha_http.StaticPathConfig = _StaticPathConfig
    ha_components.http = ha_http

    ha_loader = types.ModuleType("homeassistant.loader")
    ha_loader.async_get_loaded_integration = lambda hass, domain: None

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
        "aiohttp": aiohttp_mod,
        "aiohttp.web": aiohttp_web,
        "homeassistant.components": ha_components,
        "homeassistant.components.http": ha_http,
        "homeassistant.loader": ha_loader,
    }.items():
        sys.modules[name] = mod


_install_ha_stubs()
sys.path.insert(
    0, str(Path(__file__).resolve().parents[1] / "custom_components")
)

optimizer_mod = importlib.import_module("water_heater_optimizer.optimizer")
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

    async def async_call(self, domain, service, data, blocking=False):
        self.calls.append((domain, service, data))


class FakeHass:
    def __init__(self, states=None):
        self.states = FakeStates(states)
        self.services = FakeServices()
        self.signals = []
        self.tracked = []
        self.tasks = []

    def async_create_task(self, coro):
        task = asyncio.get_running_loop().create_task(coro)
        self.tasks.append(task)
        return task


def make_optimizer(states=None):
    entry = types.SimpleNamespace(
        data={
            "water_heater": "water_heater.test",
            "inlet_temp_sensor": "sensor.avg_inlet",
            "target_temp": 37,
            "hot_water_ratio": 0.7,
            "min_temp": 40,
            "max_temp": 50,
        },
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
    """等所有 spawn 的下发任务跑完。"""
    await asyncio.gather(*hass.tasks)


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
        await opt.async_unload()
        assert opt._listeners == []

    asyncio.run(scenario())
