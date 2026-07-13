"""Thin synchronous wrapper around tinytuya for DP 45 access.

Every method here is blocking (raw sockets via tinytuya) - callers must always
invoke these through hass.async_add_executor_job, never directly on the event
loop, and must serialize access with a lock since the underlying socket isn't
safe for concurrent use from multiple threads.
"""
import tinytuya


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

    def status(self):
        self._ensure_connected()
        return self._device.status()
