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

from .const import (
    DEFAULT_FAILSAFE_MINUTES,
    DEFAULT_SCHEDULE_CYCLE,
    DEFAULT_SCHEDULE_DURATION_MINUTES,
    DEFAULT_SCHEDULE_START_TIMES,
    DEFAULT_SCHEDULE_ZONES,
    DOMAIN,
    SCHEDULE_LISTEN_TIMEOUT,
    SCHEDULE_REFRESH_WAIT,
    ZONE_COUNT,
)
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
        # Shared "new schedule" form fields (one instance for all zones, not
        # per-zone) - written by text.py/number.py/switch.py entities, read by
        # button.py's Save/Clear buttons. Same cross-platform-lookup-avoidance
        # pattern as failsafe_minutes above. schedule_form_cycle is passed
        # straight through to tuya_dp.parse_mode as cycle_type - see its
        # docstring for the accepted formats.
        self.schedule_form_zones = DEFAULT_SCHEDULE_ZONES
        self.schedule_form_start_times = DEFAULT_SCHEDULE_START_TIMES
        self.schedule_form_duration = DEFAULT_SCHEDULE_DURATION_MINUTES
        self.schedule_form_cycle = DEFAULT_SCHEDULE_CYCLE
        self.schedule_form_rain_obey = True
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
                        self.client.receive, SCHEDULE_LISTEN_TIMEOUT
                    )
                self._maybe_handle_schedule_data(data)
            except asyncio.CancelledError:
                raise
            except Exception as err:  # noqa: BLE001 - keep the listener alive
                _LOGGER.debug("iic400: listener error, continuing: %s", err)
                await asyncio.sleep(1)

    def _maybe_handle_schedule_data(self, data):
        """Look for a DP 38 block in a raw tinytuya response and, if found,
        update the cache. Returns True if one was found. Shared by the
        background listener and async_request_schedule_refresh, which also
        needs to inspect synchronous replies - see its docstring for why."""
        if not data or not isinstance(data, dict):
            return False
        val = (data.get("dps") or {}).get(38) or (data.get("dps") or {}).get("38")
        if not val:
            return False
        self._handle_schedule_payload(val)
        return True

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
        """Prompt the device for its DP 38 blocks and wait briefly for the
        result. Some firmware embeds the pushed blocks directly in the
        updatedps() ack; others send them as separate later messages - this
        previously discarded the ack's return value entirely and relied on
        the background listener to independently catch a follow-up push
        that, on some firmware, never comes (the device only replies once,
        inside the ack). Now checks the ack first, then polls with the same
        short timeout the listener uses, up to SCHEDULE_REFRESH_WAIT total,
        before giving up."""
        async with self._lock:
            result = await self.hass.async_add_executor_job(
                self.client.request_schedule_report
            )
            if self._maybe_handle_schedule_data(result):
                return
            attempts = max(1, SCHEDULE_REFRESH_WAIT // SCHEDULE_LISTEN_TIMEOUT)
            for _ in range(attempts):
                data = await self.hass.async_add_executor_job(
                    self.client.receive, SCHEDULE_LISTEN_TIMEOUT
                )
                if self._maybe_handle_schedule_data(data):
                    return

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

    async def async_write_schedule(
        self, zones_str, duration_minutes, start_times_str, cycle_type="all", rain_obey=True
    ):
        """Build and send a DP 38 block. Shared by the iic400.set_schedule
        service and the "Save schedule" button - keeps the byte-building
        logic in exactly one place."""
        mask, _zones = tuya_dp.zones_to_mask(zones_str)
        block = tuya_dp.build_block(
            mask,
            int(duration_minutes),
            start_times_str,
            cycle_type,
            "obey" if rain_obey else "ignore",
        )
        await self.async_send_schedule(bytes(block).hex().upper())
        await self.async_request_schedule_refresh()

    async def async_clear_schedule(self, zones_str):
        """Disable the schedule for the given zones. Shared by the
        iic400.clear_schedule service and the "Clear schedule" button."""
        mask, _zones = tuya_dp.zones_to_mask(zones_str)
        block = tuya_dp.build_block(mask, 0, "", "all", "obey")
        await self.async_send_schedule(bytes(block).hex().upper())
        await self.async_request_schedule_refresh()
