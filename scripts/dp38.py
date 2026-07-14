"""Pure DP 38 (on-device schedule) byte-packing, shared by ts.py (Tuya Cloud
API) and ts_local.py (local Tuya protocol). No I/O.

DP 38 byte[0] IS ENCODED DIFFERENTLY ON WRITE VS READ - empirically
confirmed 2026-07-14 against a real IIC-400 by writing individual and
combined zones and watching what came back (not just reverse-engineered
from captures like the rest of this layout):
  - WRITE: byte[0] = bitmask 2**(zone-1), multiple bits allowed, i.e.
    z1=0x01 z2=0x02 z3=0x04 z4=0x08 (e.g. 0x03 = zones 1+2 together) -
    matches the originally-documented convention. Confirmed: a combined
    write DOES apply to all the requested zones.
  - READ (device report): byte[0] = a plain zone number 1-4, never a
    bitmask. A single-zone write is echoed back with byte[0] equal to that
    zone's plain number (e.g. sending 0x08 for zone 4 is reported back as
    byte[0]=4, not 0x08). A multi-zone write is SPLIT by the device into
    one report per zone, each with its own plain zone number and identical
    duration/time/etc - confirmed by sending 0x03 (zones 1+2) and seeing
    two separate reports, byte[0]=1 and byte[0]=2, each carrying the same
    schedule.
This was only caught because zone 3/4 exposed it; z1/z2 "worked" under a
naive same-encoding-both-ways assumption purely by coincidence, since
2**(1-1)=1 and 2**(2-1)=2 equal their own zone number.

Full byte layout:
  [0]     WRITE: bitmask 2**(zone-1) (z1=0x01 z2=0x02 z3=0x04 z4=0x08)
          READ:  plain zone number 1-4 (device-derived, see above)
  [1]     duration in minutes (0 = schedule disabled)
  [2-7]   6 start hours (0-23), 0xFF = slot unused
  [8-13]  6 start minutes (0-59), index-aligned with hours
  [14]    cycle: 0=custom days, 1=odd days, 2=even days, 3=interval
  [15]    weekday bitmap (bit0=Mon..bit6=Sun) / day count / 0
  [16-18] interval start date: YEAR-2000, MONTH, DAY (else 0)
  [19]    rain sensor: 0x11 obey / 0x00 ignore
"""
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


def parse_zone(zone):
    z = int(zone)
    if not 1 <= z <= 4:
        raise ValueError(f"invalid zone: {z}")
    return z


def parse_zone_list(zones_str):
    if zones_str.strip().lower() == "all":
        return [1, 2, 3, 4]
    return [parse_zone(tok) for tok in zones_str.split(",")]


def block_summary(b):
    if b[1] == 0:
        return "No schedule"
    starts = [f"{b[2+i]:02d}:{b[8+i]:02d}" for i in range(6) if b[2 + i] != 0xFF]
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


def parse_hhmm(token):
    hh, mm = (int(x) for x in token.split(":"))
    if not (0 <= hh <= 23 and 0 <= mm <= 59):
        raise ValueError(f"invalid time: {token}")
    return hh, mm


def parse_mode(mode_str):
    """"odd", "even", "interval:N[:YYYY-MM-DD]", or a custom-days list -
    either bare ("all", "mon,wed,fri") or "days:"-prefixed. Day names are
    case-insensitive, 3-letter or full English form."""
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


def build_block(zones, minutes, times_str, mode_str, rain_str):
    """zones is a list of plain 1-4 zone numbers; byte[0] on the wire is the
    write-side bitmask OR of 2**(zone-1) for each - see module docstring for
    why write and read use different encodings for this field, and how a
    combined write is split by the device into one report per zone."""
    b = bytearray(20)
    mask = 0
    for zone in zones:
        mask |= 1 << (zone - 1)
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
            b[2 + i] = hh
            b[8 + i] = mm
    cycle, b15, b16, b17, b18 = parse_mode(mode_str if minutes > 0 else "all")
    b[14] = cycle
    b[15] = b15 if minutes > 0 else 0x7F
    b[16], b[17], b[18] = b16, b17, b18
    rain = (rain_str or "obey").strip().lower()
    b[19] = RAIN_IGNORE if rain == "ignore" else RAIN_OBEY
    return b


def decode_block(hexstr):
    b = bytes.fromhex(hexstr)
    if len(b) != 20:
        return None
    zone = b[0] if 1 <= b[0] <= 4 else None
    return zone, block_summary(b), b
