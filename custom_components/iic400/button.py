"""Manual 'refresh schedules from device' button - prompts the device to
push its DP 38 blocks; the coordinator's listener captures the result."""
from homeassistant.components.button import ButtonEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import DeviceInfo

from .const import CONF_DEVICE_ID, DOMAIN
from .coordinator import Iic400Coordinator


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry, async_add_entities):
    coordinator: Iic400Coordinator = hass.data[DOMAIN][entry.entry_id]["coordinator"]
    async_add_entities(
        [
            Iic400ClearScheduleButton(entry, coordinator),
            Iic400SaveScheduleButton(entry, coordinator),
            Iic400RefreshSchedulesButton(entry, coordinator),
        ]
    )


class Iic400RefreshSchedulesButton(ButtonEntity):
    _attr_has_entity_name = True
    _attr_name = "13 · Refresh schedules from device"
    _attr_icon = "mdi:refresh"
    _attr_suggested_object_id = "refresh_schedules_from_device"

    def __init__(self, entry: ConfigEntry, coordinator: Iic400Coordinator):
        self._coordinator = coordinator
        device_id = entry.data[CONF_DEVICE_ID]
        self._attr_unique_id = f"{device_id}_refresh_schedules"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, device_id)},
            name=entry.title,
        )

    async def async_press(self) -> None:
        await self._coordinator.async_request_schedule_refresh()


class Iic400SaveScheduleButton(ButtonEntity):
    """Sends the shared 'new schedule' form (zones/start times/duration/cycle/
    rain switch - see text.py, number.py, select.py, switch.py) as a DP 38
    write."""

    _attr_has_entity_name = True
    _attr_name = "12 · Save schedule"
    _attr_icon = "mdi:content-save-outline"
    _attr_suggested_object_id = "save_schedule"

    def __init__(self, entry: ConfigEntry, coordinator: Iic400Coordinator):
        self._coordinator = coordinator
        device_id = entry.data[CONF_DEVICE_ID]
        self._attr_unique_id = f"{device_id}_save_schedule"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, device_id)},
            name=entry.title,
        )

    async def async_press(self) -> None:
        c = self._coordinator
        await c.async_write_schedule(
            c.schedule_form_zones,
            c.schedule_form_duration,
            c.schedule_form_start_times,
            cycle_type=c.schedule_form_cycle,
            rain_obey=c.schedule_form_rain_obey,
        )


class Iic400ClearScheduleButton(ButtonEntity):
    """Disables the on-device schedule for the zones named in the shared
    form's "Schedule zones" field (see text.py)."""

    _attr_has_entity_name = True
    _attr_name = "11 · Clear schedule"
    _attr_icon = "mdi:calendar-remove-outline"
    _attr_suggested_object_id = "clear_schedule"

    def __init__(self, entry: ConfigEntry, coordinator: Iic400Coordinator):
        self._coordinator = coordinator
        device_id = entry.data[CONF_DEVICE_ID]
        self._attr_unique_id = f"{device_id}_clear_schedule"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, device_id)},
            name=entry.title,
        )

    async def async_press(self) -> None:
        await self._coordinator.async_clear_schedule(self._coordinator.schedule_form_zones)
