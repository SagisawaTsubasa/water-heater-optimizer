"""Web layer: read-only info REST view + FumihaHub shell page registration.

Same architecture as the Stockroom panel: a zero-build custom element in
``static/``, loaded through the FumihaHub shell as a page module; data via
one read-only REST view fetched with ``hass.fetchWithAuth``. Hub-only by
design — without the shell the page is unreachable (known boundary,
per plan §2.3), logged at INFO, never silently swallowed.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from aiohttp import web
from homeassistant.components.http import (
    HomeAssistantView,
    StaticPathConfig,
    require_admin,
)
from homeassistant.const import EVENT_HOMEASSISTANT_STARTED
from homeassistant.core import Event, HomeAssistant, callback
from homeassistant.loader import async_get_loaded_integration

from .const import (
    CONF_HOT_WATER_RATIO,
    CONF_INLET_TEMP_SENSOR,
    CONF_MAX_TEMP,
    CONF_MIN_TEMP,
    CONF_TARGET_TEMP,
    CONF_WATER_HEATER,
    DOMAIN,
    HUB_BUS_EVENT_PAGE_CHANGED,
    HUB_PAGE_ID,
    HUB_PAGE_ORDER,
    HUB_PAGE_TITLE,
    HUB_REGISTRY_KEY,
)

_LOGGER = logging.getLogger(__name__)

WEB_DATA_KEY = f"{DOMAIN}_web_registered"
URL_BASE = f"/{DOMAIN}"
PANEL_ELEMENT = "water-heater-optimizer-page"
PANEL_ICON = "mdi:thermometer-auto"


class InfoView(HomeAssistantView):
    """GET /api/water_heater_optimizer/info — read-only page payload."""

    url = f"/api/{DOMAIN}/info"
    name = f"api:{DOMAIN}:info"
    requires_auth = True

    @require_admin
    async def get(self, request: web.Request) -> web.Response:
        """One entry per optimizer instance; all fields read-only."""
        hass = request.app["hass"]
        entries = []
        for entry_id, opt in (hass.data.get(DOMAIN) or {}).items():
            entries.append({
                "entry_id": entry_id,
                "water_heater": opt.config.get(CONF_WATER_HEATER),
                "inlet_temp_sensor": opt.config.get(CONF_INLET_TEMP_SENSOR),
                "target_temp": opt.config.get(CONF_TARGET_TEMP),
                "hot_water_ratio": opt.config.get(CONF_HOT_WATER_RATIO),
                "min_temp": opt.config.get(CONF_MIN_TEMP),
                "max_temp": opt.config.get(CONF_MAX_TEMP),
                "last_avg_temp": opt.last_avg_temp,
                "recommended_temp": opt.recommended_temp,
                "applied_temp": opt.applied_temp,
                "auto_adjust": opt.auto_adjust,
            })
        return self.json({"entries": entries})


def _manifest_version(hass: HomeAssistant) -> str:
    try:
        return async_get_loaded_integration(hass, DOMAIN).version or "dev"
    except Exception:  # noqa: BLE001 — version is only a cache buster
        _LOGGER.debug("Could not resolve integration version for panel URL")
        return "dev"


def _descriptor(version: str) -> dict[str, Any]:
    """Hub-shell page descriptor (fumiha_hub registry contract)."""
    return {
        "id": HUB_PAGE_ID,
        "title": HUB_PAGE_TITLE,
        "icon": PANEL_ICON,
        "order": HUB_PAGE_ORDER,
        "version": version,
        "module_url": f"{URL_BASE}/panel.js?ver={version}",
        "element": PANEL_ELEMENT,
    }


@callback
def _register_page(hass: HomeAssistant, flags: dict) -> None:
    """Register the page into the hub shell registry, if the shell is loaded.

    探针 = HUB_REGISTRY_KEY 键存在 ⇔ 壳条目已加载且未删除（契约由
    fumiha_hub/registry.py 保证）；绝不自己创建该 dict。无壳时跳过注册
    （页面不可达为已知边界，计划书 §2.3），INFO 落因且整个会话只记一次。
    每次调用都按在场性补注册：壳条目删了又加会销毁重建 registry dict，
    只看上次标记会漏（SR-F-083 同族）。
    """
    registry = hass.data.get(HUB_REGISTRY_KEY)
    if registry is None:
        if not flags.get("hub_absent_logged"):
            _LOGGER.info("未检测到文羽面板壳（fumiha_hub），信息页暂不注册")
            flags["hub_absent_logged"] = True
        flags["page_registered"] = False
        return
    if HUB_PAGE_ID not in registry:
        registry[HUB_PAGE_ID] = _descriptor(_manifest_version(hass))
        hass.bus.async_fire(
            HUB_BUS_EVENT_PAGE_CHANGED, {"id": HUB_PAGE_ID, "action": "register"}
        )
        _LOGGER.info("热水器优化器信息页已注册到文羽面板壳（%s）", HUB_PAGE_ID)
    flags["page_registered"] = True


@callback
def _teardown_page(hass: HomeAssistant) -> None:
    registry = hass.data.get(HUB_REGISTRY_KEY)
    if registry is not None and registry.pop(HUB_PAGE_ID, None) is not None:
        hass.bus.async_fire(
            HUB_BUS_EVENT_PAGE_CHANGED,
            {"id": HUB_PAGE_ID, "action": "unregister"},
        )


def _make_started_recheck(hass: HomeAssistant, flags: dict):
    @callback
    def _recheck(event: Event) -> None:
        # R1 P3#6（WHA-F-334 同型）：一次性监听触发后 HA 已自动移除，
        # 置 None 防 unload 时再 unsub 报 "Unable to remove unknown job listener"
        flags["started_recheck"] = None
        _LOGGER.debug("HA started: re-checking hub page registration")
        _register_page(hass, flags)

    return _recheck


def _make_page_watch(hass: HomeAssistant, flags: dict):
    @callback
    def _watch(event: Event) -> None:
        # R1 P3#9：壳条目删后重加会销毁重建 registry dict（fumiha_hub 的
        # async_remove_entry 删键、再 setup 建新 dict），我们注册的页会丢且
        # 契约无 registry-ready 事件；借任何消费者的注册/注销活动重查补注册。
        # shortcut: 壳重建后若无任何消费者活动，仍需本集成 reload 才恢复
        # （fumiha_hub registry 契约明示 consumers re-register on next reload）
        _register_page(hass, flags)

    return _watch


async def async_setup_web(hass: HomeAssistant) -> None:
    """Register static assets, info view and the hub page (once per HA run)."""
    flags: dict = hass.data.setdefault(WEB_DATA_KEY, {})

    if not flags.get("views"):
        hass.http.register_view(InfoView())
        flags["views"] = True

    if not flags.get("static"):
        static_dir = Path(__file__).parent / "static"
        await hass.http.async_register_static_paths(
            [StaticPathConfig(URL_BASE, str(static_dir), cache_headers=False)]
        )
        flags["static"] = True

    _register_page(hass, flags)

    if not flags.get("started_recheck") and not hass.is_running:
        # 壳条目可能晚于本集成加载；started 时全量就位，重查一次。
        # HA 已运行（条目 reload 重进此处）时不再挂一次性监听——started
        # 不会再触发，挂着只是死监听
        flags["started_recheck"] = hass.bus.async_listen_once(
            EVENT_HOMEASSISTANT_STARTED, _make_started_recheck(hass, flags)
        )

    if not flags.get("page_watch"):
        # R1 P3#9：常驻重查监听——壳删后重加重建 registry 时借消费者活动补注册
        flags["page_watch"] = hass.bus.async_listen(
            HUB_BUS_EVENT_PAGE_CHANGED, _make_page_watch(hass, flags)
        )


@callback
def async_unload_web(hass: HomeAssistant) -> None:
    """Tear down the hub page when the last entry unloads.

    Views and static paths survive entry reloads (registered once per HA
    run, guarded by the flags in hass.data[WEB_DATA_KEY]).
    """
    flags: dict = hass.data.get(WEB_DATA_KEY) or {}
    if not flags:
        return
    if (unsub := flags.pop("page_watch", None)) is not None:
        # 先摘重查监听，防 teardown 的 page_changed 广播被自己接住而重注册
        unsub()
    if flags.get("page_registered"):
        _teardown_page(hass)
        flags["page_registered"] = False
    if (unsub := flags.pop("started_recheck", None)) is not None:
        # 已触发的一次性监听已被 HA 移除且 flags 里已置 None，这里只处理
        # "注册了但从未触发"的残留
        unsub()
