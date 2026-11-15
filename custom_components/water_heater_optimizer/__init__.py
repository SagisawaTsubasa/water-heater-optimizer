"""Water Heater Optimizer integration."""

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.typing import ConfigType

from .const import (
    CONF_HOT_WATER_RATIO,
    CONF_MAX_TEMP,
    CONF_MIN_TEMP,
    CONF_TARGET_TEMP,
    DOMAIN,
)
from .optimizer import WaterHeaterOptimizer

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[Platform] = [Platform.SENSOR, Platform.SWITCH, Platform.NUMBER]

# 可由 number 实体运行时直接改的键：仅这些键变化时不重载条目，走热应用
_LIVE_KEYS = frozenset({
    CONF_TARGET_TEMP,
    CONF_HOT_WATER_RATIO,
    CONF_MIN_TEMP,
    CONF_MAX_TEMP,
})


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Set up the integration."""
    hass.data.setdefault(DOMAIN, {})
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up a config entry."""
    optimizer = WaterHeaterOptimizer(hass, entry)
    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = optimizer

    @callback
    def _cleanup() -> None:
        # R1 P2#3：setup 失败与正常卸载共用回滚。HA 在 setup 抛错时会执行
        # on_unload 链（config_entries 的 async_setup finally 分支），挂上后
        # 平台转发失败不再泄漏 hass.data 条目与 avg listener。
        # 幂等：正常卸载（unload platforms 成功后 on_unload 链）二次调用空跑
        optimizer.stop()
        hass.data.get(DOMAIN, {}).pop(entry.entry_id, None)

    entry.async_on_unload(_cleanup)

    await optimizer.async_setup()

    # Reload the entry automatically when options are changed
    entry.async_on_unload(entry.add_update_listener(_async_update_listener))

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    return True


async def _async_update_listener(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Handle options update.

    只有可调参数（目标温度/热水比例/推荐窗口上下限）变化时热应用，避免拖动 number
    实体触发整条目重载（实体瞬间不可用 + 监听重建）；标题、data 等
    结构性变化（实体配置来源）仍走完整重载。
    """
    optimizer = hass.data.get(DOMAIN, {}).get(entry.entry_id)
    if optimizer is not None:
        changed = {
            k
            for k in set(optimizer.last_options) | set(entry.options)
            if optimizer.last_options.get(k) != entry.options.get(k)
        }
        structural = (
            entry.title != optimizer.last_title or entry.data != optimizer.last_data
        )
        if not changed and not structural:
            # 残留的重复通知（或仅无影响字段变化），无须任何处理；
            # 这道早退守卫保证热应用路径不会被重复回调打回重载
            return
        if not structural and changed <= _LIVE_KEYS:
            optimizer.apply_live_config()
            return
    # async_schedule_reload 把重载放进任务并先取消 setup retry，消除竞态
    hass.config_entries.async_schedule_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry.

    条目清理（stop/pop hass.data）统一走 async_setup_entry 里
    注册的 on_unload 回调：unload platforms 成功后 HA 自动执行 on_unload
    链；失败时保留现场（与旧行为一致）。
    """
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
