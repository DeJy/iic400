"""Zone start/stop switches.

State tracks the real device (tuya-local's "zones running" sensor bitmask),
not local command-tracking - so it stays correct even if a zone is stopped by
the physical device buttons, the Inkbird app, a rain-sensor skip, or a fault.
A short debounce smooths over tuya-local reconnect blips right after we write
a DP (see const.ZONE_STATE_DELAY_ON/OFF), mirroring the previous
template binary_sensor delay_on/delay_off.

turn_on/turn_off also set _attr_is_on optimistically the moment the DP is
sent, instead of waiting for the sensor round-trip. Without this, the
frontend's optimistic toggle gets contradicted by our own unchanged state
right as the service call returns (flips back), then corrected again once the
sensor debounce fires - a visible on/off/on flicker. The sensor-driven
debounce above remains the actual source of truth: it silently confirms the
optimistic guess when the sensor agrees, and overrides it if the device
disagrees (e.g. a failed write). This isn't the "local command-tracking"
that's discouraged above - it's a prediction that the real tracking still
verifies, not a replacement for it.

turn_on starts ONLY the targeted zone, using coordinator.failsafe_minutes as a
safety-net duration (the calling automation times the run itself and calls
turn_off; the failsafe just guards against a missed turn_off, e.g. an HA
restart mid-run).

turn_off sends the DP 45 stop-all command. This is a hardware limitation, not
a choice: DP 45's stop halts every manual zone at once, there is no verified
way to stop a single zone while others keep running. Because state here is
read from the real device sensor, all 4 switches will correctly show "off"
together when this happens - don't try to "fix" that by only clearing local
state for the zone that was clicked. Only run one zone at a time.

Since only one zone can ever be running, turning a zone on (or off) also
optimistically flips every *other* zone switch to off in the same call -
otherwise a sibling that was running would sit "on" for the full debounce
window even though it demonstrably can't still be running. See
coordinator.zone_switches, populated below in async_setup_entry.
"""
import logging

from homeassistant.components.switch import SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.event import async_call_later, async_track_state_change_event
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import (
    CONF_DEVICE_ID,
    CONF_ZONES_RUNNING_ENTITY_ID,
    DOMAIN,
    MANUFACTURER,
    MODEL,
    ZONE_COUNT,
    ZONE_STATE_DELAY_OFF,
    ZONE_STATE_DELAY_ON,
)
from .coordinator import Iic400Coordinator
from . import tuya_dp

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry, async_add_entities):
    coordinator: Iic400Coordinator = hass.data[DOMAIN][entry.entry_id]["coordinator"]
    zone_switches = [Iic400ZoneSwitch(entry, coordinator, zone) for zone in range(1, ZONE_COUNT + 1)]
    coordinator.zone_switches = zone_switches
    async_add_entities(zone_switches)


class Iic400ZoneSwitch(CoordinatorEntity, SwitchEntity):
    _attr_has_entity_name = True
    _attr_icon = "mdi:sprinkler"

    def __init__(self, entry: ConfigEntry, coordinator: Iic400Coordinator, zone: int):
        super().__init__(coordinator)
        self._entry = entry
        self._zone = zone
        self._bit = 1 << (zone - 1)
        self._source_sensor = entry.data[CONF_ZONES_RUNNING_ENTITY_ID]
        device_id = entry.data[CONF_DEVICE_ID]
        self._attr_name = f"0{zone} · Zone {zone}"
        self._attr_suggested_object_id = f"zone_{zone}"
        self._attr_unique_id = f"{device_id}_zone_{zone}_switch"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, device_id)},
            name=entry.title,
            manufacturer=MANUFACTURER,
            model=MODEL,
        )
        self._attr_is_on = False
        self._cancel_debounce = None

    async def async_added_to_hass(self):
        await super().async_added_to_hass()
        self.async_on_remove(
            async_track_state_change_event(
                self.hass, [self._source_sensor], self._handle_source_change
            )
        )
        # Prime from whatever the sensor currently reports.
        current = self.hass.states.get(self._source_sensor)
        if current is not None:
            self._apply_bit(self._bit_from_state(current.state), immediate=True)

    def _bit_from_state(self, raw_state):
        try:
            return (int(raw_state) & self._bit) > 0
        except (TypeError, ValueError):
            _LOGGER.warning(
                "%s: source entity %s has a non-numeric state (%r) - it must be "
                "the raw zones-running bitmask sensor, not the human-readable "
                "enum one. Reconfigure the integration and pick the '... raw' "
                "sensor.",
                self.entity_id,
                self._source_sensor,
                raw_state,
            )
            return False

    @callback
    def _handle_source_change(self, event):
        new_state = event.data.get("new_state")
        if new_state is None:
            return
        self._apply_bit(self._bit_from_state(new_state.state))

    def _apply_bit(self, new_value, immediate=False):
        if new_value == self._attr_is_on:
            if self._cancel_debounce is not None:
                self._cancel_debounce()
                self._cancel_debounce = None
            return
        if self._cancel_debounce is not None:
            self._cancel_debounce()
            self._cancel_debounce = None

        if immediate:
            self._attr_is_on = new_value
            self.async_write_ha_state()
            return

        delay = ZONE_STATE_DELAY_ON if new_value else ZONE_STATE_DELAY_OFF

        @callback
        def _commit(_now):
            self._cancel_debounce = None
            self._attr_is_on = new_value
            self.async_write_ha_state()

        self._cancel_debounce = async_call_later(self.hass, delay, _commit)

    def _set_optimistic(self, new_value):
        if self._cancel_debounce is not None:
            self._cancel_debounce()
            self._cancel_debounce = None
        self._attr_is_on = new_value
        self.async_write_ha_state()

    async def _send(self, payload, active_zone):
        # active_zone is the zone number left running afterwards, or None if
        # this is a stop-all. Only one zone can ever run, so every switch -
        # not just this one - gets its optimistic value set in the same pass.
        switches = self.coordinator.zone_switches or [self]
        previous = {s: s._attr_is_on for s in switches}
        for s in switches:
            s._set_optimistic(s._zone == active_zone)
        try:
            await self.coordinator.async_send_manual(payload)
        except Exception:
            # Send failed - the device state never changed, so no sensor
            # event will ever arrive to correct these guesses. Revert them.
            for s, prev in previous.items():
                s._set_optimistic(prev)
            raise

    async def async_turn_on(self, **kwargs):
        durations = [0] * ZONE_COUNT
        durations[self._zone - 1] = self.coordinator.failsafe_minutes
        payload = tuya_dp.build_manual(durations)
        await self._send(payload, self._zone)

    async def async_turn_off(self, **kwargs):
        payload = tuya_dp.build_stop()
        await self._send(payload, None)
