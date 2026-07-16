"""Core optimizer logic."""

import logging
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.event import (
    async_track_state_change_event,
    async_track_time_change,
    async_call_later,
)
from homeassistant.helpers.dispatcher import async_dispatcher_send
from homeassistant.util import dt as dt_util

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
    TRIGGER_TYPE_ENTITY_STATE,
    TRIGGER_TYPE_DURATION,
    TRIGGER_TYPE_FIXED_TIME,
    SIGNAL_UPDATE,
)

_LOGGER = logging.getLogger(__name__)


class WaterHeaterOptimizer:
    """Manage temperature optimization for a single water heater."""

    def __init__(self, hass: HomeAssistant, entry):
        self.hass = hass
        self.entry = entry
        self.config = entry.data
        self.recommended_temp = None
        self.reference_tap_temp = None
        self.session_min_temp = None
        self.water_start_ts = None
        self.auto_adjust = False
        self._listeners = []
        self._duration_timer = None
        self._signal = f"{SIGNAL_UPDATE}_{entry.entry_id}"

    def calculate(self, tap_temp: float | None) -> int | None:
        """Calculate recommended heater temperature."""
        if tap_temp is None:
            return None

        target = self.config.get(CONF_TARGET_TEMP, DEFAULT_TARGET_TEMP)
        ratio = self.config.get(CONF_HOT_WATER_RATIO, DEFAULT_RATIO)
        min_temp = self.config.get(CONF_MIN_TEMP, DEFAULT_MIN_TEMP)
        max_temp = self.config.get(CONF_MAX_TEMP, DEFAULT_MAX_TEMP)

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

    async def async_unload(self):
        """Remove all listeners."""
        for unsub in self._listeners:
            unsub()
        self._listeners.clear()
        if self._duration_timer:
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

        @callback
        def _state_changed(event):
            new = event.data.get("new_state")
            if new is None:
                return

            if to_state and new.state != to_state:
                if self._duration_timer:
                    self._duration_timer()
                    self._duration_timer = None
                return

            self._duration_timer = async_call_later(
                self.hass, duration, lambda _: self.snapshot()
            )

        self._listeners.append(
            async_track_state_change_event(self.hass, entity, _state_changed)
        )

    async def _setup_fixed_time_trigger(self):
        """Trigger at a fixed time every day."""
        time_str = self.config.get(CONF_TRIGGER_TIME, "06:00")
        try:
            hour, minute = map(int, time_str.split(":"))
        except ValueError:
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
        if state is None or state.state in ("unknown", "unavailable", "none", ""):
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
            self.hass.async_create_task(self._apply_temperature())

    async def _apply_temperature(self):
        """Apply recommended temperature to water heater."""
        await self.hass.services.async_call(
            "water_heater",
            "set_temperature",
            {
                "entity_id": self.config[CONF_WATER_HEATER],
                "temperature": self.recommended_temp,
            },
            blocking=False,
        )

    async def async_set_auto_adjust(self, enabled: bool):
        """Enable or disable auto-adjust."""
        self.auto_adjust = enabled
        if enabled and self.recommended_temp is not None:
            await self._apply_temperature()
        async_dispatcher_send(self.hass, self._signal)
