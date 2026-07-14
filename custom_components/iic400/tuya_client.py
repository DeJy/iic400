"""Thin synchronous wrapper around tinytuya for DP 45 / DP 38 access.

Every method here is blocking (raw sockets via tinytuya) - callers must always
invoke these through hass.async_add_executor_job, never directly on the event
loop, and must serialize access with a lock since the underlying socket isn't
safe for concurrent use from multiple threads.
"""
import logging

import tinytuya

_LOGGER = logging.getLogger(__name__)


class Iic400TuyaClient:
    def __init__(self, device_id, host, local_key, version):
        self._device_id = device_id
        self._host = host
        self._local_key = local_key
        self._version = version
        self._device = None

    def connect(self):
        self._device = tinytuya.Device(
            self._device_id, self._host, self._local_key, version=self._version
        )
        self._device.set_socketTimeout(10)

    def close(self):
        if self._device is not None:
            try:
                self._device.close()
            except Exception:  # noqa: BLE001 - best-effort cleanup
                pass
            self._device = None

    def _ensure_connected(self):
        if self._device is None:
            self.connect()

    def send_manual(self, payload_b64):
        """Write a DP 45 payload (base64 string)."""
        self._ensure_connected()
        self._device.set_value("45", payload_b64)

    def request_schedule_report(self):
        """Ask the device to push its current DP 38 blocks. Returns whatever
        tinytuya hands back synchronously - some firmware embeds the first
        pushed block directly in this reply rather than sending it as a
        separate later message, so callers must not discard it. In practice
        the device rarely answers here at all (see receive()) - this is a
        nudge, not a guaranteed answer."""
        self._ensure_connected()
        return self._device.updatedps(["38"])

    def send_schedule(self, hex_payload):
        """Write a DP 38 payload (uppercase hex string) for one or more
        zones (bitmask in byte[0] - see tuya_dp.py)."""
        self._ensure_connected()
        self._device.set_value("38", hex_payload)

    def receive(self, timeout=2):
        """Block for up to `timeout` seconds waiting for a device push.
        Returns the raw dict tinytuya hands back, or None on timeout/error.
        """
        self._ensure_connected()
        self._device.set_socketTimeout(timeout)
        try:
            return self._device.receive()
        except Exception as err:  # noqa: BLE001 - socket timeouts, resets, etc.
            _LOGGER.debug("iic400: receive() failed, will retry: %s", err)
            self.close()
            return None

    def status(self):
        self._ensure_connected()
        return self._device.status()
