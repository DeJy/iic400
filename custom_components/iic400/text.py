"""Shared 'new schedule' form text fields - zones, start times, and cycle -
one instance for all zones (not per-zone). Values live on the coordinator
(mirrors number.py's failsafe-minutes pattern) so button.py's Save/Clear
buttons can read them without a fragile cross-platform entity_id lookup.
"""
from homeassistant.components.text import TextEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.restore_state import RestoreEntity

from .const import CONF_DEVICE_ID, DOMAIN
from .coordinator import Iic400Coordinator


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry, async_add_entities):
    coordinator: Iic400Coordinator = hass.data[DOMAIN][entry.entry_id]["coordinator"]
    async_add_entities(
        [
            Iic400ScheduleZonesText(entry, coordinator),
            Iic400ScheduleStartTimesText(entry, coordinator),
            Iic400ScheduleCycleText(entry, coordinator),
        ]
    )


class _ScheduleFormText(RestoreEntity, TextEntity):
    _attr_has_entity_name = True
    _coordinator_attr = None  # set by subclasses

    def __init__(self, entry: ConfigEntry, coordinator: Iic400Coordinator):
        self._coordinator = coordinator
        device_id = entry.data[CONF_DEVICE_ID]
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, device_id)},
            name=entry.title,
        )

    @property
    def native_value(self):
        return getattr(self._coordinator, self._coordinator_attr)

    async def async_added_to_hass(self):
        await super().async_added_to_hass()
        last_state = await self.async_get_last_state()
        if last_state is not None and last_state.state not in (None, "unknown", "unavailable"):
            setattr(self._coordinator, self._coordinator_attr, last_state.state)

    async def async_set_value(self, value: str) -> None:
        setattr(self._coordinator, self._coordinator_attr, value)
        self.async_write_ha_state()


class Iic400ScheduleZonesText(_ScheduleFormText):
    _attr_name = "06 · Schedule zones"
    _attr_icon = "mdi:selection-ellipse-arrow-inside"
    _attr_suggested_object_id = "schedule_zones"
    _coordinator_attr = "schedule_form_zones"

    def __init__(self, entry: ConfigEntry, coordinator: Iic400Coordinator):
        super().__init__(entry, coordinator)
        device_id = entry.data[CONF_DEVICE_ID]
        self._attr_unique_id = f"{device_id}_schedule_zones"


class Iic400ScheduleStartTimesText(_ScheduleFormText):
    _attr_name = "07 · Schedule start times"
    _attr_icon = "mdi:clock-plus-outline"
    _attr_suggested_object_id = "schedule_start_times"
    _coordinator_attr = "schedule_form_start_times"

    def __init__(self, entry: ConfigEntry, coordinator: Iic400Coordinator):
        super().__init__(entry, coordinator)
        device_id = entry.data[CONF_DEVICE_ID]
        self._attr_unique_id = f"{device_id}_schedule_start_times"


class Iic400ScheduleCycleText(_ScheduleFormText):
    """Cycle-type field of the shared 'new schedule' form. Free text passed
    straight through to tuya_dp.parse_mode as cycle_type - see its
    docstring: "days:all", "days:Monday,Wednesday,Friday" (or 3-letter
    abbreviations), "odd", "even", or "interval:N[:YYYY-MM-DD]"."""

    _attr_name = "09 · Schedule cycle"
    _attr_icon = "mdi:calendar-sync-outline"
    _attr_suggested_object_id = "schedule_cycle"
    _coordinator_attr = "schedule_form_cycle"

    def __init__(self, entry: ConfigEntry, coordinator: Iic400Coordinator):
        super().__init__(entry, coordinator)
        device_id = entry.data[CONF_DEVICE_ID]
        self._attr_unique_id = f"{device_id}_schedule_cycle"
