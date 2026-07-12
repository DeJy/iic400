"""Per-zone schedule summary sensors, sourced from the coordinator's passively
captured DP 38 cache - never opens a device connection on its own."""
from homeassistant.components.sensor import SensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import CONF_DEVICE_ID, DOMAIN, ZONE_COUNT
from .coordinator import Iic400Coordinator


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
        self._attr_name = f"Zone {zone} schedule"
        self._attr_unique_id = f"{device_id}_zone_{zone}_schedule"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, device_id)},
            name=entry.title,
        )

    @property
    def native_value(self):
        block = self.coordinator.data["schedules"].get(self._zone)
        return block["summary"] if block else "unknown"

    @property
    def extra_state_attributes(self):
        block = self.coordinator.data["schedules"].get(self._zone)
        if not block:
            return {}
        return {"raw": block["raw"], "updated_at": block["updated_at"]}
