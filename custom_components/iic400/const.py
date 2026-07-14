"""Constants for the Inkbird IIC-400 Irrigation integration."""

DOMAIN = "iic400"
TUYA_LOCAL_DOMAIN = "tuya_local"

ZONE_COUNT = 4

DP_MANUAL = "45"
DP_SCHEDULE = "38"

CONF_SOURCE_ENTRY_ID = "source_entry_id"
CONF_DEVICE_ID = "device_id"
CONF_LOCAL_KEY = "local_key"
CONF_HOST = "host"
CONF_PROTOCOL_VERSION = "protocol_version"
CONF_ZONES_RUNNING_ENTITY_ID = "zones_running_entity_id"

DEFAULT_FAILSAFE_MINUTES = 180
MIN_FAILSAFE_MINUTES = 1
MAX_FAILSAFE_MINUTES = 1440

# Debounce, mirrors the old template binary_sensor delay_on/delay_off - smooths
# over tuya-local reconnect blips right after we write a DP. Switch turn_on/
# turn_off set state optimistically first, so this delay is purely a
# background reconciliation window against the real sensor, not something the
# user waits through visually.
ZONE_STATE_DELAY_ON = 10
ZONE_STATE_DELAY_OFF = 10

# DP 38 has no per-zone query - the device pushes whichever zone-group
# blocks it feels like, on its own schedule. SCHEDULE_LISTEN_TIMEOUT is the
# per-receive() socket timeout while collecting pushes; SCHEDULE_REFRESH_WAIT
# is the total time a refresh keeps listening before giving up on zones that
# haven't answered; SCHEDULE_RENUDGE_INTERVAL re-sends the query that often
# in case the first nudge only prompted some zones. Empirically (2026-07-14,
# see scripts/ts_local.py): zone 4 in particular can take 60-80s to answer,
# hence the generous default wait.
SCHEDULE_LISTEN_TIMEOUT = 2
SCHEDULE_REFRESH_WAIT = 90
SCHEDULE_RENUDGE_INTERVAL = 10

SERVICE_QUICK_WATER = "quick_water"
SERVICE_SET_SCHEDULE = "set_schedule"
SERVICE_CLEAR_SCHEDULE = "clear_schedule"
