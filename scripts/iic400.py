#!/usr/bin/env python3
"""Local control of the Inkbird IIC-400-WIFI sprinkler controller
(Tuya local protocol 3.5). Protocol fully reverse-engineered and
hardware-validated, 2026-07-10.

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
  [10-17] single-use time, same layout. Stop: [0]=1, rest zero.

NOTES:
  - One write per command invocation (simple and reliable).
  - The internal schedule clock is synced by the Inkbird app only.
  - A JSON cache of schedules (iic400_schedules.json) is kept next to
    this script; Home Assistant reads it to display schedules without
    opening a device connection.

Usage:
  iic400.py start <zone> <minutes> | multi <m1> <m2> <m3> <m4> | stop
  iic400.py status | schedules
  iic400.py schedule <zones> <min> <HH:MM[,...]> [mode] [obey|ignore]
  iic400.py schedule <zones> off
  <zones>: "2" | "1,3" | "all"
  Modes: all | mon,wed,fri | odd | even | interval:N[:YYYY-MM-DD]
"""
import sys
import os
import json
import base64
import time
import datetime

sys.path.insert(0, "/config/scripts/lib")
import tinytuya  # noqa: E402

# --- Credentials -----------------------------------------------------
# Source 1 (priority): iic400_secrets.json next to this script.
# Source 2 (auto):     the tuya-local config entry in Home Assistant's
#   registry (/config/.storage/core.config_entries). Single source of
#   truth: reconfiguring the device in tuya-local updates this script
#   too. Internal HA format, may change between versions, hence the
#   file fallback. NEVER commit .storage/ to git.
SECRETS_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                            "iic400_secrets.json")
HA_ENTRIES = "/config/.storage/core.config_entries"
DEVICE_MATCH = "iic"   # pick the tuya-local device whose title
                       # contains this text (case-insensitive)


def _load_from_ha():
    with open(HA_ENTRIES) as f:
        entries = json.load(f)["data"]["entries"]
    tl = [e for e in entries if e.get("domain") == "tuya_local"]
    if not tl:
        raise RuntimeError("no tuya_local device in the HA registry")
    pick = next((e for e in tl
                 if DEVICE_MATCH in (e.get("title") or "").lower()), tl[0])
    d = pick.get("data", {})
    dev_id = d.get("device_id")
    key = d.get("local_key")
    host = d.get("host") or d.get("ip") or d.get("address")
    ver = d.get("protocol_version") or d.get("version") or 3.5
    if not (dev_id and key and host):
        raise RuntimeError(f"missing fields in entry "
                           f"'{pick.get('title')}': {sorted(d.keys())}")
    if str(ver) == "auto":
        ver = 3.5
    return dev_id, host, key, float(ver)


try:
    if os.path.exists(SECRETS_FILE):
        with open(SECRETS_FILE) as _f:
            _s = json.load(_f)
        DEVICE_ID = _s["device_id"]
        DEVICE_IP = _s["device_ip"]
        LOCAL_KEY = _s["local_key"]      # changes after every re-pairing!
        VERSION = float(_s.get("version", 3.5))
    else:
        DEVICE_ID, DEVICE_IP, LOCAL_KEY, VERSION = _load_from_ha()
except Exception as _e:
    sys.exit(f"Credentials not found: {_e}\n"
             f"Either create {SECRETS_FILE} (see .example) or make sure "
             f"the device is configured in tuya-local.")

CACHE = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                     "iic400_schedules.json")
DAY_NAMES = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]
CYCLE_NAMES = {0: "custom days", 1: "odd days", 2: "even days",
               3: "interval"}
RAIN_OBEY = 0x11
RAIN_IGNORE = 0x00


def device():
    d = tinytuya.Device(DEVICE_ID, DEVICE_IP, LOCAL_KEY, version=VERSION)
    d.set_socketTimeout(10)
    return d


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


# ---------- schedules cache (read by Home Assistant) ----------

def cache_load():
    if os.path.exists(CACHE):
        try:
            with open(CACHE) as f:
                return json.load(f)
        except Exception:
            pass
    return {}


def cache_update(zones, summary, raw_hex):
    c = cache_load()
    now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
    for z in zones:
        c[str(z)] = {"summary": summary, "raw": raw_hex, "updated": now}
    try:
        with open(CACHE, "w") as f:
            json.dump(c, f, ensure_ascii=False, indent=1)
    except Exception as e:
        print(f"(cache not written: {e})")


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


# ---------- manual run (DP 45) ----------

def build_manual(minutes_per_zone):
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


# ---------- schedules (DP 38) ----------

def parse_hhmm(token):
    hh, mm = (int(x) for x in token.split(":"))
    if not (0 <= hh <= 23 and 0 <= mm <= 59):
        raise ValueError(f"invalid time: {token}")
    return hh, mm


def parse_mode(mode_str):
    mode = (mode_str or "all").strip().lower()
    if mode == "odd":
        return 1, 0, 0, 0, 0
    if mode == "even":
        return 2, 0, 0, 0, 0
    if mode.startswith("interval:"):
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
    bitmap = 0
    days = DAY_NAMES if mode in ("all", "") else mode.split(",")
    for j in days:
        j = j.strip().lower()
        if j not in DAY_NAMES:
            raise ValueError(f"invalid day: {j}")
        bitmap |= 1 << DAY_NAMES.index(j)
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
    try:
        b = bytes.fromhex(hexstr)
    except ValueError:
        return f"  (not decodable: {hexstr})"
    if len(b) != 20:
        return f"  (unexpected length: {hexstr})"
    zones = mask_to_zones(b[0])
    ztxt = "+".join(str(z) for z in zones) if zones else f"0x{b[0]:02X}?"
    return f"Zone(s) {ztxt}: {block_summary(b)}\n  raw: {hexstr}"


def read_schedules():
    d = device()
    print("Reading schedules (passive)...")
    seen = {}
    try:
        st = d.status()
        if isinstance(st, dict):
            val = (st.get("dps") or {}).get("38")
            if val:
                seen[val[:2].upper()] = val.upper()
    except Exception:
        pass
    for _ in range(3):
        try:
            d.updatedps(["38"])
        except Exception:
            pass
        deadline = time.time() + 6
        while time.time() < deadline:
            try:
                data = d.receive()
            except Exception:
                break
            if data and isinstance(data, dict):
                val = (data.get("dps") or {}).get("38")
                if val:
                    seen[val[:2].upper()] = val.upper()
        if len(seen) >= 4:
            break
    for k in sorted(seen):
        hexstr = seen[k]
        print(decode_block(hexstr))
        b = bytes.fromhex(hexstr)
        if len(b) == 20:
            cache_update(mask_to_zones(b[0]), block_summary(b), hexstr)
    if not seen:
        print("(nothing received - retry)")
    elif len(seen) < 4:
        print(f"({len(seen)}/4 blocks received - retry to complete)")


# ---------- main ----------

def main():
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)
    cmd = sys.argv[1].lower()

    if cmd == "start":
        zone, minutes = int(sys.argv[2]), int(sys.argv[3])
        if not 1 <= zone <= 4:
            sys.exit("Invalid zone (1-4)")
        durations = [0, 0, 0, 0]
        durations[zone - 1] = minutes
        device().set_value(45, build_manual(durations))
        print(f"Zone {zone} started for {minutes} min")

    elif cmd == "multi":
        durations = [int(x) for x in sys.argv[2:6]]
        device().set_value(45, build_manual(durations))
        print(f"Zones started: {durations} (minutes)")

    elif cmd == "stop":
        b = bytearray(18)
        b[0] = 1
        device().set_value(45, base64.b64encode(bytes(b)).decode())
        print("Manual irrigation stopped")

    elif cmd == "status":
        print(device().status())

    elif cmd == "schedules":
        read_schedules()

    elif cmd == "schedule":
        try:
            mask, zones = zones_to_mask(sys.argv[2])
            if sys.argv[3].lower() == "off":
                b = build_block(mask, 0, "", "all", "obey")
            else:
                b = build_block(
                    mask, int(sys.argv[3]), sys.argv[4],
                    sys.argv[5] if len(sys.argv) > 5 else "all",
                    sys.argv[6] if len(sys.argv) > 6 else "obey")
        except (ValueError, IndexError) as e:
            sys.exit(f"invalid arguments: {e}")
        hexstr = bytes(b).hex().upper()
        print(decode_block(hexstr))
        device().set_value(38, hexstr)
        cache_update(zones, block_summary(b), hexstr)
        print(f"Sent (zones {zones}), cache updated. Verify with"
              " 'schedules' or by behavior.")

    else:
        print(__doc__)
        sys.exit(1)


if __name__ == "__main__":
    main()