"""Coordinator for the Inkbird IIC-400 Irrigation integration.

Schedule data (DP 38) is pushed by the device, not polled - this coordinator
keeps a long-lived background listener task running for the life of the
config entry to passively catch whatever the device pushes on its own, and
separately supports an explicit "refresh" (button press, or automatically
after a write) that marks the targeted zones "pending" and actively
re-nudges the device while listening, since DP 38 has no per-zone query -
see const.py and tuya_dp.py for the write/read encoding this all assumes.
"""
import asyncio
import logging

from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator
from homeassistant.util import dt as dt_util

from .const import (
    DEFAULT_FAILSAFE_MINUTES,
    DOMAIN,
    SCHEDULE_LISTEN_TIMEOUT,
    SCHEDULE_REFRESH_WAIT,
    SCHEDULE_RENUDGE_INTERVAL,
    ZONE_COUNT,
)
from .tuya_client import Iic400TuyaClient
from . import tuya_dp

_LOGGER = logging.getLogger(__name__)

PENDING = "pending"


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
        # Per zone: None (never read), PENDING (refresh in progress, no
        # answer yet), or {"summary", "raw", "updated_at"} once known.
        self.data = {"schedules": {z: None for z in range(1, ZONE_COUNT + 1)}}

    async def _async_update_data(self):
        # Connectivity check only - schedule data arrives via the listener
        # and async_request_schedule_refresh.
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
        decode and cache it. Returns the zone number if one was found and
        decoded, else None. Shared by the background listener and
        async_request_schedule_refresh."""
        if not data or not isinstance(data, dict):
            return None
        val = (data.get("dps") or {}).get(38) or (data.get("dps") or {}).get("38")
        if not val:
            return None
        decoded = tuya_dp.decode_block(val)
        if decoded is None:
            return None
        zone, summary, _ = decoded
        self.data["schedules"][zone] = {
            "summary": summary,
            "raw": val,
            "updated_at": dt_util.now(),
        }
        self.async_set_updated_data(self.data)
        return zone

    async def async_request_schedule_refresh(self, zones=None):
        """Mark `zones` (default: all 4) as pending, then prompt the device
        and actively listen/re-nudge for up to SCHEDULE_REFRESH_WAIT,
        updating each zone's sensor the moment its block arrives rather than
        waiting for the whole window. DP 38 has no per-zone query - a zone
        that never answers within the window has its "Pending…" cleared and
        reverts to whatever it showed before this refresh started (its last
        known value, or "Unknown" if it never had one) rather than getting
        stuck on "Pending…" forever after we've stopped actually listening
        for it."""
        targets = set(zones) if zones else set(range(1, ZONE_COUNT + 1))
        previous = {
            z: self.data["schedules"][z]
            for z in targets
            if self.data["schedules"][z] != PENDING
        }
        for zone in targets:
            self.data["schedules"][zone] = PENDING
        self.async_set_updated_data(self.data)

        def _still_pending():
            return {z for z in targets if self.data["schedules"][z] == PENDING}

        async with self._lock:
            ack = await self.hass.async_add_executor_job(
                self.client.request_schedule_report
            )
            self._maybe_handle_schedule_data(ack)

        deadline = self.hass.loop.time() + SCHEDULE_REFRESH_WAIT
        next_nudge = self.hass.loop.time() + SCHEDULE_RENUDGE_INTERVAL
        while _still_pending() and self.hass.loop.time() < deadline:
            if self.hass.loop.time() >= next_nudge:
                async with self._lock:
                    ack = await self.hass.async_add_executor_job(
                        self.client.request_schedule_report
                    )
                    self._maybe_handle_schedule_data(ack)
                next_nudge = self.hass.loop.time() + SCHEDULE_RENUDGE_INTERVAL
            async with self._lock:
                data = await self.hass.async_add_executor_job(
                    self.client.receive, SCHEDULE_LISTEN_TIMEOUT
                )
            self._maybe_handle_schedule_data(data)

        timed_out = _still_pending()
        if timed_out:
            for zone in timed_out:
                self.data["schedules"][zone] = previous.get(zone)
            self.async_set_updated_data(self.data)

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
        service and (if re-added later) any dashboard form - keeps the
        byte-building logic in exactly one place."""
        mask, zones = tuya_dp.zones_to_mask(zones_str)
        block = tuya_dp.build_block(
            mask,
            int(duration_minutes),
            start_times_str,
            cycle_type,
            "obey" if rain_obey else "ignore",
        )
        await self.async_send_schedule(bytes(block).hex().upper())
        await self.async_request_schedule_refresh(zones)

    async def async_clear_schedule(self, zones_str):
        """Disable the schedule for the given zones."""
        mask, zones = tuya_dp.zones_to_mask(zones_str)
        block = tuya_dp.build_block(mask, 0, "", "all", "obey")
        await self.async_send_schedule(bytes(block).hex().upper())
        await self.async_request_schedule_refresh(zones)
