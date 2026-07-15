"""Per-zone schedule summary sensors, sourced from the coordinator's
passively-captured-or-refreshed DP 38 cache - never opens a device
connection on their own.

Each sensor shows one of four states:
  - "Unknown"   - never read since HA started (no refresh done yet, and the
                  device hasn't spontaneously pushed this zone's block)
  - "Pending…"  - a refresh is in progress and this zone hasn't answered yet
  - "Try Again" - a refresh timed out after SCHEDULE_REFRESH_WAIT without an
                  answer for this zone
  - the schedule summary text (e.g. "10 min @ 06:00 - every day") once known
"""
from homeassistant.components.sensor import SensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import CONF_DEVICE_ID, DOMAIN, MANUFACTURER, MODEL, ZONE_COUNT
from .coordinator import PENDING, TRY_AGAIN, Iic400Coordinator


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry, async_add_entities):
    coordinator: Iic400Coordinator = hass.data[DOMAIN][entry.entry_id]["coordinator"]
    async_add_entities(
        [
            Iic400ZoneScheduleSensor(entry, coordinator, zone)
            for zone in range(1, ZONE_COUNT + 1)
        ]
    )


class Iic400ZoneScheduleSensor(CoordinatorEntity, SensorEntity):
    _attr_has_entity_name = True
    _attr_icon = "mdi:calendar-clock"

    def __init__(self, entry: ConfigEntry, coordinator: Iic400Coordinator, zone: int):
        super().__init__(coordinator)
        self._zone = zone
        device_id = entry.data[CONF_DEVICE_ID]
        self._attr_name = f"0{5 + zone} · Zone {zone} schedule"
        self._attr_suggested_object_id = f"zone_{zone}_schedule"
        self._attr_unique_id = f"{device_id}_zone_{zone}_schedule"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, device_id)},
            name=entry.title,
            manufacturer=MANUFACTURER,
            model=MODEL,
        )

    @property
    def native_value(self):
        block = self.coordinator.data["schedules"].get(self._zone)
        if block is None:
            return "Unknown"
        if block == PENDING:
            return "Pending…"
        if block == TRY_AGAIN:
            return "Try Again"
        return block["summary"]

    @property
    def extra_state_attributes(self):
        block = self.coordinator.data["schedules"].get(self._zone)
        if not block or block in (PENDING, TRY_AGAIN):
            return {}
        return {"raw": block["raw"], "updated_at": block["updated_at"]}
