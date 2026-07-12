"""Coordinator for the Inkbird IIC-400 Irrigation integration.

Schedule data (DP 38) is pushed by the device, not polled - this coordinator
keeps a long-lived background listener task running for the life of the
config entry and pushes updates via async_set_updated_data whenever a DP 38
block arrives, rather than using DataUpdateCoordinator's normal fixed-interval
polling.
"""
import asyncio
import logging

from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator
from homeassistant.util import dt as dt_util

from .const import DEFAULT_FAILSAFE_MINUTES, DOMAIN, ZONE_COUNT
from .tuya_client import Iic400TuyaClient
from . import tuya_dp

_LOGGER = logging.getLogger(__name__)


class Iic400Coordinator(DataUpdateCoordinator):
    def __init__(self, hass: HomeAssistant, client: Iic400TuyaClient):
        super().__init__(hass, _LOGGER, name=DOMAIN, update_interval=None)
        self.client = client
        self._lock = asyncio.Lock()
        self._listener_task = None
        # Read by switch.py, written by number.py's failsafe-minutes entity -
        # avoids fragile cross-platform entity_id lookups.
        self.failsafe_minutes = DEFAULT_FAILSAFE_MINUTES
        # Populated by switch.py's async_setup_entry. Only one zone can run
        # at a time, so a switch turning on/off needs to optimistically flip
        # its siblings too, not just itself - this is how they find each other.
        self.zone_switches = []
        self.data = {"schedules": {z: None for z in range(1, ZONE_COUNT + 1)},
                      "last_schedule_update": None}

    async def _async_update_data(self):
        # Connectivity check only - schedule data arrives via the listener.
        async with self._lock:
            await self.hass.async_add_executor_job(self.client.status)
        return self.data

    def async_start_listener(self):
        self._listener_task = self.hass.loop.create_task(self._listen_loop())

    async def async_stop_listener(self):
        if self._listener_task is not None:
            self._listener_task.cancel()
            try:
                await self._listener_task
            except asyncio.CancelledError:
                pass
            self._listener_task = None

    async def _listen_loop(self):
        while True:
            try:
                async with self._lock:
                    data = await self.hass.async_add_executor_job(
                        self.client.receive, 2
                    )
                if data and isinstance(data, dict):
                    val = (data.get("dps") or {}).get(38) or (data.get("dps") or {}).get("38")
                    if val:
                        self._handle_schedule_payload(val)
            except asyncio.CancelledError:
                raise
            except Exception as err:  # noqa: BLE001 - keep the listener alive
                _LOGGER.debug("iic400: listener error, continuing: %s", err)
                await asyncio.sleep(1)

    def _handle_schedule_payload(self, hexstr):
        decoded = tuya_dp.decode_block(hexstr)
        if decoded is None:
            return
        zones, summary, _ = decoded
        updated_at = dt_util.now()
        for zone in zones:
            self.data["schedules"][zone] = {
                "summary": summary,
                "raw": hexstr,
                "updated_at": updated_at,
            }
        self.data["last_schedule_update"] = updated_at
        self.async_set_updated_data(self.data)

    async def async_request_schedule_refresh(self, zone=None):
        async with self._lock:
            await self.hass.async_add_executor_job(
                self.client.request_schedule_report
            )

    async def async_send_manual(self, payload_b64):
        async with self._lock:
            await self.hass.async_add_executor_job(
                self.client.send_manual, payload_b64
            )

    async def async_send_schedule(self, hex_payload):
        async with self._lock:
            await self.hass.async_add_executor_job(
                self.client.send_schedule, hex_payload
            )
