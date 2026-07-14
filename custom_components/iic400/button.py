"""Manual 'refresh schedules from device' button - prompts the device to
push its DP 38 blocks; marks all 4 zone-schedule sensors "Pending…" and
fills each in live as its block arrives (up to const.SCHEDULE_REFRESH_WAIT).
Writing schedules is done via the iic400.set_schedule / iic400.clear_schedule
services (see services.yaml), not a dashboard form.
"""
from homeassistant.components.button import ButtonEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import DeviceInfo

from .const import CONF_DEVICE_ID, DOMAIN
from .coordinator import Iic400Coordinator


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry, async_add_entities):
    coordinator: Iic400Coordinator = hass.data[DOMAIN][entry.entry_id]["coordinator"]
    async_add_entities([Iic400RefreshSchedulesButton(entry, coordinator)])


class Iic400RefreshSchedulesButton(ButtonEntity):
    _attr_has_entity_name = True
    _attr_name = "10 · Refresh schedules from device"
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
