"""Failsafe duration helper entity - replaces input_number.iic400_failsafe_minutes.

The current value lives on the coordinator (coordinator.failsafe_minutes) so
switch.py can read it without a fragile cross-platform entity_id lookup.
"""
from homeassistant.components.number import NumberEntity, NumberMode
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.restore_state import RestoreEntity

from .const import (
    CONF_DEVICE_ID,
    DEFAULT_FAILSAFE_MINUTES,
    DOMAIN,
    MANUFACTURER,
    MAX_FAILSAFE_MINUTES,
    MIN_FAILSAFE_MINUTES,
    MODEL,
)
from .coordinator import Iic400Coordinator


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry, async_add_entities):
    coordinator: Iic400Coordinator = hass.data[DOMAIN][entry.entry_id]["coordinator"]
    async_add_entities([Iic400FailsafeMinutesNumber(entry, coordinator)])


class Iic400FailsafeMinutesNumber(RestoreEntity, NumberEntity):
    _attr_has_entity_name = True
    _attr_name = "05 · Zone switch failsafe duration"
    _attr_icon = "mdi:timer-alert"
    _attr_suggested_object_id = "zone_switch_failsafe_duration"
    _attr_native_min_value = MIN_FAILSAFE_MINUTES
    _attr_native_max_value = MAX_FAILSAFE_MINUTES
    _attr_native_step = 1
    _attr_native_unit_of_measurement = "min"
    _attr_mode = NumberMode.BOX

    def __init__(self, entry: ConfigEntry, coordinator: Iic400Coordinator):
        self._coordinator = coordinator
        device_id = entry.data[CONF_DEVICE_ID]
        self._attr_unique_id = f"{device_id}_failsafe_minutes"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, device_id)},
            name=entry.title,
            manufacturer=MANUFACTURER,
            model=MODEL,
        )

    @property
    def native_value(self):
        return self._coordinator.failsafe_minutes

    async def async_added_to_hass(self):
        await super().async_added_to_hass()
        last_state = await self.async_get_last_state()
        if last_state is not None and last_state.state not in (None, "unknown", "unavailable"):
            try:
                self._coordinator.failsafe_minutes = float(last_state.state)
            except ValueError:
                self._coordinator.failsafe_minutes = DEFAULT_FAILSAFE_MINUTES

    async def async_set_native_value(self, value: float) -> None:
        self._coordinator.failsafe_minutes = value
        self.async_write_ha_state()
