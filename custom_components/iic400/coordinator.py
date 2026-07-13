"""Coordinator for the Inkbird IIC-400 Irrigation integration."""
import asyncio
import logging

from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator

from .const import DEFAULT_FAILSAFE_MINUTES, DOMAIN
from .tuya_client import Iic400TuyaClient

_LOGGER = logging.getLogger(__name__)


class Iic400Coordinator(DataUpdateCoordinator):
    def __init__(self, hass: HomeAssistant, client: Iic400TuyaClient):
        super().__init__(hass, _LOGGER, name=DOMAIN, update_interval=None)
        self.client = client
        self._lock = asyncio.Lock()
        # Read by switch.py, written by number.py's failsafe-minutes entity -
        # avoids fragile cross-platform entity_id lookups.
        self.failsafe_minutes = DEFAULT_FAILSAFE_MINUTES
        # Populated by switch.py's async_setup_entry. Only one zone can run
        # at a time, so a switch turning on/off needs to optimistically flip
        # its siblings too, not just itself - this is how they find each other.
        self.zone_switches = []

    async def _async_update_data(self):
        async with self._lock:
            await self.hass.async_add_executor_job(self.client.status)
        return None

    async def async_send_manual(self, payload_b64):
        async with self._lock:
            await self.hass.async_add_executor_job(
                self.client.send_manual, payload_b64
            )
