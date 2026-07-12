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
    async_add_entities([Iic400RefreshSchedulesButton(entry, coordinator)])


class Iic400RefreshSchedulesButton(ButtonEntity):
    _attr_has_entity_name = True
    _attr_name = "Refresh schedules from device"
    _attr_icon = "mdi:refresh"

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
