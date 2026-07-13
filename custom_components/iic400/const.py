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

# Defaults for the shared "new schedule" form entities (one instance for all
# zones, not per-zone) - see text.py/number.py/select.py/switch.py/button.py.
DEFAULT_SCHEDULE_ZONES = "1"
DEFAULT_SCHEDULE_START_TIMES = "06:00"
DEFAULT_SCHEDULE_DURATION_MINUTES = 10
MIN_SCHEDULE_DURATION_MINUTES = 1
MAX_SCHEDULE_DURATION_MINUTES = 99

# Schedule cycle select - a simplified front end for iic400.set_schedule's
# cycle_type string. Covers all/odd/even/interval; custom weekday combos
# (e.g. "mon,wed,fri") and an interval start date other than today still
# require the service call - not worth a dropdown option each.
SCHEDULE_CYCLE_ALL = "All days"
SCHEDULE_CYCLE_ODD = "Odd days"
SCHEDULE_CYCLE_EVEN = "Even days"
SCHEDULE_CYCLE_INTERVAL = "Every N days"
SCHEDULE_CYCLE_OPTIONS = [
    SCHEDULE_CYCLE_ALL,
    SCHEDULE_CYCLE_ODD,
    SCHEDULE_CYCLE_EVEN,
    SCHEDULE_CYCLE_INTERVAL,
]
DEFAULT_SCHEDULE_CYCLE = SCHEDULE_CYCLE_ALL
# Maps the select's display option to tuya_dp.parse_mode's cycle_type prefix.
# SCHEDULE_CYCLE_INTERVAL is handled separately (needs schedule_form_interval_days).
SCHEDULE_CYCLE_TO_TYPE = {
    SCHEDULE_CYCLE_ALL: "all",
    SCHEDULE_CYCLE_ODD: "odd",
    SCHEDULE_CYCLE_EVEN: "even",
}
DEFAULT_SCHEDULE_INTERVAL_DAYS = 2
MIN_SCHEDULE_INTERVAL_DAYS = 1
MAX_SCHEDULE_INTERVAL_DAYS = 99

# Debounce, mirrors the old template binary_sensor delay_on/delay_off - smooths
# over tuya-local reconnect blips right after we write a DP. Switch turn_on/
# turn_off set state optimistically first, so this delay is purely a
# background reconciliation window against the real sensor, not something the
# user waits through visually.
ZONE_STATE_DELAY_ON = 10
ZONE_STATE_DELAY_OFF = 10

SCHEDULE_LISTEN_TIMEOUT = 2
SCHEDULE_REFRESH_WAIT = 6

SERVICE_SET_SCHEDULE = "set_schedule"
SERVICE_CLEAR_SCHEDULE = "clear_schedule"
SERVICE_QUICK_WATER = "quick_water"
