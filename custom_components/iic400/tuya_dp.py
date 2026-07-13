"""Pure DP 38 (schedules) / DP 45 (manual run) byte-packing for the Inkbird
IIC-400-WIFI. No I/O, no Home Assistant imports - ported from the standalone
scripts/iic400.py so it can be unit-checked in isolation.

DP 38 FORMAT (schedules, 20 bytes per block):
  [0]     zone BITMASK: z1=0x01 z2=0x02 z3=0x04 z4=0x08 (multi allowed)
  [1]     duration in minutes (0 = schedule disabled)
  [2-7]   6 start hours (0-23), 0xFF = slot unused
  [8-13]  6 start minutes (0-59), index-aligned with hours
  [14]    cycle: 0=custom days, 1=odd days, 2=even days, 3=interval
  [15]    weekday bitmap (bit0=Mon..bit6=Sun) / day count / 0
  [16-18] interval start date: YEAR-2000, MONTH, DAY (else 0)
  [19]    rain sensor: 0x11 obey / 0x00 ignore

DP 45 FORMAT (manual run, 18 bytes, base64):
  [0]=1 start/reset, [1]=1 specific zones,
  [2-9] run time per zone (2 bytes BE, minutes, z1..z4),
  [10-17] single-use time, same layout. Stop: [0]=1, rest zero - this stops
  ALL manual zones at once, not a single zone (hardware behavior).

  Hardware-confirmed 2026-07-12: sending this exact layout (zone 1, 1
  minute) flipped DP 101 (operation mode) to "Manual" on its own and set
  DP 107's zone-1 bit, i.e. the zone actually ran. An alternate layout
  hypothesized from a differently-captured trace (flag at [1] only, no
  duplicated [10-17] block) was tested back-to-back on the same device and
  did *not* start the zone or flip the mode - rejected. The layout
  implemented below is the one to use; no open discrepancy remains.
"""
import base64
import datetime

DAY_NAMES = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]
FULL_DAY_NAMES = [
    "monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday",
]
DAY_NAME_TO_INDEX = {
    **{name: i for i, name in enumerate(DAY_NAMES)},
    **{name: i for i, name in enumerate(FULL_DAY_NAMES)},
}
CYCLE_NAMES = {0: "custom days", 1: "odd days", 2: "even days", 3: "interval"}
RAIN_OBEY = 0x11
RAIN_IGNORE = 0x00


def zones_to_mask(zones_str):
    if zones_str.strip().lower() == "all":
        return 0x0F, [1, 2, 3, 4]
    mask, zone_list = 0, []
    for tok in zones_str.split(","):
        z = int(tok.strip())
        if not 1 <= z <= 4:
            raise ValueError(f"invalid zone: {z}")
        mask |= 1 << (z - 1)
        zone_list.append(z)
    return mask, sorted(set(zone_list))


def mask_to_zones(mask):
    return [z for z in (1, 2, 3, 4) if mask & (1 << (z - 1))]


def block_summary(b):
    if b[1] == 0:
        return "No schedule"
    starts = [f"{b[2+i]:02d}:{b[8+i]:02d}" for i in range(6)
              if b[2 + i] != 0xFF]
    cycle = b[14] & 0x03
    if cycle == 0:
        days = [DAY_NAMES[i] for i in range(7) if b[15] & (1 << i)]
        when = ",".join(days) if len(days) < 7 else "every day"
    elif cycle == 3:
        when = f"every {b[15]} d from 20{b[16]:02d}-{b[17]:02d}-{b[18]:02d}"
    else:
        when = CYCLE_NAMES[cycle]
    rain = " (ignores rain)" if b[19] == RAIN_IGNORE else ""
    return f"{b[1]} min @ {', '.join(starts)} - {when}{rain}"


def build_manual(minutes_per_zone):
    """Build the 18-byte DP 45 payload (base64-encoded) for a manual run.

    minutes_per_zone: list of up to 4 ints (minutes for zone 1..4). Use 0 for
    zones that should not (re)start - the device only auto-stops zones with a
    nonzero duration once it elapses.
    """
    b = bytearray(18)
    b[0] = 1
    b[1] = 1
    for i, minutes in enumerate(minutes_per_zone[:4]):
        m = max(0, int(minutes))
        b[2 + i * 2] = (m >> 8) & 0xFF
        b[3 + i * 2] = m & 0xFF
        b[10 + i * 2] = (m >> 8) & 0xFF
        b[11 + i * 2] = m & 0xFF
    return base64.b64encode(bytes(b)).decode()


def build_stop():
    """Build the DP 45 stop-all payload (base64). Stops every manual zone at
    once - there is no verified hardware behavior for stopping a single zone
    while others keep running. Do not build a per-zone stop without testing
    against real hardware first.
    """
    b = bytearray(18)
    b[0] = 1
    return base64.b64encode(bytes(b)).decode()


def parse_hhmm(token):
    hh, mm = (int(x) for x in token.split(":"))
    if not (0 <= hh <= 23 and 0 <= mm <= 59):
        raise ValueError(f"invalid time: {token}")
    return hh, mm


def parse_mode(mode_str):
    """Parse a cycle_type string: "odd", "even", "interval:N[:YYYY-MM-DD]",
    or a custom-days list - either bare ("all", "mon,wed,fri") or
    "days:"-prefixed ("days:all", "days:Monday,Wednesday,Friday"; day names
    are case-insensitive and accept either 3-letter or full English form).
    The "days:" prefix exists only to make the free-text schedule-cycle
    entity (see text.py) unambiguous next to "odd"/"even"/"interval:...";
    both forms are accepted everywhere for backward compatibility.
    """
    mode = (mode_str or "all").strip()
    lower = mode.lower()
    if lower == "odd":
        return 1, 0, 0, 0, 0
    if lower == "even":
        return 2, 0, 0, 0, 0
    if lower.startswith("interval:"):
        parts = mode.split(":")
        every = int(parts[1])
        if not 1 <= every <= 99:
            raise ValueError("invalid interval (1-99)")
        if len(parts) >= 3:
            y, m, dd = (int(x) for x in parts[2].split("-"))
            start = datetime.date(y, m, dd)
        else:
            start = datetime.date.today()
        return 3, every, start.year % 100, start.month, start.day
    days_part = mode[len("days:"):] if lower.startswith("days:") else mode
    days_part = days_part.strip()
    bitmap = 0
    days = DAY_NAMES if days_part.lower() in ("all", "") else days_part.split(",")
    for j in days:
        j = j.strip().lower()
        idx = DAY_NAME_TO_INDEX.get(j)
        if idx is None:
            raise ValueError(f"invalid day: {j}")
        bitmap |= 1 << idx
    return 0, bitmap, 0, 0, 0


def build_block(mask, minutes, times_str, mode_str, rain_str):
    b = bytearray(20)
    b[0] = mask
    b[1] = minutes
    for i in range(2, 14):
        b[i] = 0xFF
    if minutes > 0:
        tokens = [x.strip() for x in times_str.split(",") if x.strip()]
        if not tokens:
            raise ValueError("at least one start time required")
        if len(tokens) > 6:
            raise ValueError("max 6 start times")
        for i, tok in enumerate(tokens):
            hh, mm = parse_hhmm(tok)
            b[2 + i] = hh    # hours block  (bytes 2-7)
            b[8 + i] = mm    # minutes block (bytes 8-13)
    cycle, b15, b16, b17, b18 = parse_mode(mode_str if minutes > 0 else "all")
    b[14] = cycle
    b[15] = b15 if minutes > 0 else 0x7F
    b[16], b[17], b[18] = b16, b17, b18
    rain = (rain_str or "obey").strip().lower()
    b[19] = RAIN_IGNORE if rain == "ignore" else RAIN_OBEY
    return b


def decode_block(hexstr):
    """Decode a 20-byte DP 38 hex string into (zones, summary) or None if
    not decodable/wrong length."""
    try:
        b = bytes.fromhex(hexstr)
    except ValueError:
        return None
    if len(b) != 20:
        return None
    zones = mask_to_zones(b[0])
    return zones, block_summary(b), b
