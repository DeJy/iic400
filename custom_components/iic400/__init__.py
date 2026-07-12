"""The Inkbird IIC-400 Irrigation integration."""
import logging

import voluptuous as vol

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers import device_registry as dr

from .const import (
    CONF_DEVICE_ID,
    CONF_HOST,
    CONF_LOCAL_KEY,
    CONF_PROTOCOL_VERSION,
    DOMAIN,
    SERVICE_CLEAR_SCHEDULE,
    SERVICE_QUICK_WATER,
    SERVICE_SET_SCHEDULE,
)
from .coordinator import Iic400Coordinator
from .tuya_client import Iic400TuyaClient
from . import tuya_dp

_LOGGER = logging.getLogger(__name__)

PLATFORMS = ["switch", "number", "sensor", "button"]


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    data = entry.data
    client = Iic400TuyaClient(
        data[CONF_DEVICE_ID],
        data[CONF_HOST],
        data[CONF_LOCAL_KEY],
        data[CONF_PROTOCOL_VERSION],
    )
    coordinator = Iic400Coordinator(hass, client)
    await coordinator.async_config_entry_first_refresh()
    coordinator.async_start_listener()

    hass.data.setdefault(DOMAIN, {})
    hass.data[DOMAIN][entry.entry_id] = {"coordinator": coordinator, "client": client}

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    _async_register_services(hass)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    unloaded = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unloaded:
        stored = hass.data[DOMAIN].pop(entry.entry_id)
        await stored["coordinator"].async_stop_listener()
        stored["client"].close()
    return unloaded


def _coordinator_for_device(hass: HomeAssistant, device_id: str) -> Iic400Coordinator:
    device_registry = dr.async_get(hass)
    device = device_registry.async_get(device_id)
    if device is None:
        raise ValueError(f"Unknown device_id: {device_id}")
    for entry_id in device.config_entries:
        stored = hass.data.get(DOMAIN, {}).get(entry_id)
        if stored is not None:
            return stored["coordinator"]
    raise ValueError(f"device_id {device_id} is not an iic400 device")


def _async_register_services(hass: HomeAssistant) -> None:
    if hass.services.has_service(DOMAIN, SERVICE_SET_SCHEDULE):
        return

    async def _set_schedule(call: ServiceCall) -> None:
        coordinator = _coordinator_for_device(hass, call.data["device_id"])
        mask, zones = tuya_dp.zones_to_mask(call.data["zones"])
        block = tuya_dp.build_block(
            mask,
            int(call.data["duration_minutes"]),
            call.data["start_times"],
            call.data.get("cycle_type", "all"),
            "obey" if call.data.get("rain_obey", True) else "ignore",
        )
        await coordinator.async_send_schedule(bytes(block).hex().upper())
        await coordinator.async_request_schedule_refresh()

    async def _clear_schedule(call: ServiceCall) -> None:
        coordinator = _coordinator_for_device(hass, call.data["device_id"])
        mask, zones = tuya_dp.zones_to_mask(call.data["zones"])
        block = tuya_dp.build_block(mask, 0, "", "all", "obey")
        await coordinator.async_send_schedule(bytes(block).hex().upper())
        await coordinator.async_request_schedule_refresh()

    async def _quick_water(call: ServiceCall) -> None:
        coordinator = _coordinator_for_device(hass, call.data["device_id"])
        zone = int(call.data["zone"])
        durations = [0, 0, 0, 0]
        durations[zone - 1] = int(call.data["duration_minutes"])
        await coordinator.async_send_manual(tuya_dp.build_manual(durations))

    hass.services.async_register(
        DOMAIN,
        SERVICE_SET_SCHEDULE,
        _set_schedule,
        schema=vol.Schema(
            {
                vol.Required("device_id"): cv.string,
                vol.Required("zones"): cv.string,
                vol.Required("duration_minutes"): vol.Coerce(int),
                vol.Required("start_times"): cv.string,
                vol.Optional("cycle_type", default="all"): cv.string,
                vol.Optional("rain_obey", default=True): cv.boolean,
            },
            extra=vol.ALLOW_EXTRA,
        ),
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_CLEAR_SCHEDULE,
        _clear_schedule,
        schema=vol.Schema(
            {
                vol.Required("device_id"): cv.string,
                vol.Required("zones"): cv.string,
            },
            extra=vol.ALLOW_EXTRA,
        ),
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_QUICK_WATER,
        _quick_water,
        schema=vol.Schema(
            {
                vol.Required("device_id"): cv.string,
                vol.Required("zone"): vol.Coerce(int),
                vol.Required("duration_minutes"): vol.Coerce(int),
            },
            extra=vol.ALLOW_EXTRA,
        ),
    )
