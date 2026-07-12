"""Config flow for the Inkbird IIC-400 Irrigation integration.

Rather than asking the user to re-enter device_id/local_key/host, this flow
lists the tuya_local config entries already on the system and lets the user
pick the one for their IIC-400 - credentials are copied out of that entry's
data. It then locates that device's "zones running" sensor via the entity
registry (with a manual override) so zone switches can track real device
state instead of locally-assumed state.
"""
import logging

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers import selector

from .const import (
    CONF_DEVICE_ID,
    CONF_HOST,
    CONF_LOCAL_KEY,
    CONF_PROTOCOL_VERSION,
    CONF_SOURCE_ENTRY_ID,
    CONF_ZONES_RUNNING_ENTITY_ID,
    DOMAIN,
    TUYA_LOCAL_DOMAIN,
)

_LOGGER = logging.getLogger(__name__)


def _guess_zones_running_entity(hass, source_entry_id):
    """Best-effort guess at the tuya_local 'zones running' sensor for this
    device, used only to pre-fill the picker - never trusted blindly."""
    registry = er.async_get(hass)
    candidates = [
        entry
        for entry in er.async_entries_for_config_entry(registry, source_entry_id)
        if entry.domain == "sensor"
        and "zone" in (entry.entity_id or "").lower()
        and "running" in (entry.entity_id or "").lower()
    ]
    if len(candidates) == 1:
        return candidates[0].entity_id
    return None


class Iic400ConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    VERSION = 1

    def __init__(self):
        self._source_entry = None
        self._device_data = {}

    async def async_step_user(self, user_input=None):
        tuya_entries = self.hass.config_entries.async_entries(TUYA_LOCAL_DOMAIN)
        if not tuya_entries:
            return self.async_abort(reason="no_tuya_local_entries")

        if user_input is not None:
            self._source_entry = self.hass.config_entries.async_get_entry(
                user_input[CONF_SOURCE_ENTRY_ID]
            )
            if self._source_entry is None:
                return self.async_abort(reason="no_tuya_local_entries")

            data = self._source_entry.data
            device_id = data.get(CONF_DEVICE_ID)
            local_key = data.get(CONF_LOCAL_KEY)
            host = data.get(CONF_HOST) or data.get("ip") or data.get("address")
            version = data.get(CONF_PROTOCOL_VERSION) or data.get("version") or 3.5
            if str(version) == "auto":
                version = 3.5

            if not (device_id and local_key and host):
                return self.async_abort(reason="incomplete_tuya_local_entry")

            await self.async_set_unique_id(device_id)
            self._abort_if_unique_id_configured()

            self._device_data = {
                CONF_SOURCE_ENTRY_ID: self._source_entry.entry_id,
                CONF_DEVICE_ID: device_id,
                CONF_LOCAL_KEY: local_key,
                CONF_HOST: host,
                CONF_PROTOCOL_VERSION: float(version),
            }
            return await self.async_step_zones_sensor()

        options = {
            entry.entry_id: entry.title or entry.entry_id for entry in tuya_entries
        }
        schema = vol.Schema(
            {vol.Required(CONF_SOURCE_ENTRY_ID): vol.In(options)}
        )
        return self.async_show_form(step_id="user", data_schema=schema)

    async def async_step_zones_sensor(self, user_input=None):
        if user_input is not None:
            self._device_data[CONF_ZONES_RUNNING_ENTITY_ID] = user_input[
                CONF_ZONES_RUNNING_ENTITY_ID
            ]
            return self.async_create_entry(
                title=self._source_entry.title or "IIC-400 Irrigation",
                data=self._device_data,
            )

        suggested = _guess_zones_running_entity(
            self.hass, self._source_entry.entry_id
        )
        schema = vol.Schema(
            {
                vol.Required(
                    CONF_ZONES_RUNNING_ENTITY_ID,
                    description={"suggested_value": suggested} if suggested else None,
                ): selector.EntitySelector(
                    selector.EntitySelectorConfig(domain="sensor")
                )
            }
        )
        return self.async_show_form(step_id="zones_sensor", data_schema=schema)
