"""Cycle-type field of the shared 'new schedule' form (see text.py/number.py)
- one instance for all zones, not per-zone. A simplified front end for
iic400.set_schedule's cycle_type string: custom weekday combos (e.g.
"mon,wed,fri") and an interval start date other than today aren't
representable in a dropdown and still require the service call.
"""
from homeassistant.components.select import SelectEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.restore_state import RestoreEntity

from .const import CONF_DEVICE_ID, DEFAULT_SCHEDULE_CYCLE, DOMAIN, SCHEDULE_CYCLE_OPTIONS
from .coordinator import Iic400Coordinator


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry, async_add_entities):
    coordinator: Iic400Coordinator = hass.data[DOMAIN][entry.entry_id]["coordinator"]
    async_add_entities([Iic400ScheduleCycleSelect(entry, coordinator)])


class Iic400ScheduleCycleSelect(RestoreEntity, SelectEntity):
    _attr_has_entity_name = True
    _attr_name = "09 · Schedule cycle"
    _attr_icon = "mdi:calendar-sync-outline"
    _attr_suggested_object_id = "schedule_cycle"
    _attr_options = SCHEDULE_CYCLE_OPTIONS

    def __init__(self, entry: ConfigEntry, coordinator: Iic400Coordinator):
        self._coordinator = coordinator
        device_id = entry.data[CONF_DEVICE_ID]
        self._attr_unique_id = f"{device_id}_schedule_cycle"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, device_id)},
            name=entry.title,
        )

    @property
    def current_option(self):
        return self._coordinator.schedule_form_cycle

    async def async_added_to_hass(self):
        await super().async_added_to_hass()
        last_state = await self.async_get_last_state()
        if last_state is not None and last_state.state in SCHEDULE_CYCLE_OPTIONS:
            self._coordinator.schedule_form_cycle = last_state.state
        else:
            self._coordinator.schedule_form_cycle = DEFAULT_SCHEDULE_CYCLE

    async def async_select_option(self, option: str) -> None:
        self._coordinator.schedule_form_cycle = option
        self.async_write_ha_state()
