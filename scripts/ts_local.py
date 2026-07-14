#!/usr/bin/env python3
"""Manual CLI to read/write the IIC-400's on-device schedule (DP 38) over the
local (LAN) Tuya protocol via tinytuya.Device - the same protocol
custom_components/iic400/tuya_client.py uses for DP 45, but standalone and
NOT part of that HA integration, which deliberately does not manage
schedules. Run by hand only. See ts.py for the same tool over the Tuya
Cloud API instead.

Credentials come from secrets.yaml at the repo root (gitignored):
    device: <Tuya device id>
    local_key: <Tuya local key>
    ip: <device's LAN IP>
    version: <protocol version, e.g. 3.5 - optional, defaults to 3.5>

Usage:
    python scripts/ts_local.py read [--timeout N] [--renudge N]
    python scripts/ts_local.py write --zones 1,3 --duration 10 \
        --times 06:00,18:00 --cycle days:mon,wed,fri --rain obey
    python scripts/ts_local.py clear --zones 1,3

`read` note: unlike the cloud API, the local protocol has no report
history to search, and DP 38 has no per-zone query - there is no field to
say "just zone 3", the zone is encoded inside the pushed payload itself,
which the device chooses to send on its own schedule (confirmed
empirically: `updatedps(["38"])`'s ack rarely carries the DP 38 value
itself - it showed an unrelated DP instead - the actual blocks arrive a
moment later as separate pushes, and not every zone necessarily pushes in
a single burst; zone 4 in particular tends to report last, sometimes 60-80s
in). `read` re-sends that query every --renudge seconds (default 10) while
listening for up to --timeout seconds (default 90), printing each zone's
block live as it arrives instead of waiting silently. A zone that never
gets pushed in that window (usually because no schedule was ever written
to it) won't show up - rerun with a longer --timeout, or `write` it once
first.

DP 38 byte layout and the write/read encoding quirk (confirmed against the
cloud API on 2026-07-14) are documented in dp38.py. This script assumes the
same quirk applies locally (both talk to the same device firmware) but that
has NOT been separately empirically re-confirmed over the local protocol -
double check a write's effect with `read` before trusting it blindly.

Requires: tinytuya, pyyaml (pip install tinytuya pyyaml)
"""
import argparse
import json
import pathlib
import sys
import time

import tinytuya
import yaml

import dp38

SECRETS_PATH = pathlib.Path(__file__).resolve().parent.parent / "secrets.yaml"
DEFAULT_VERSION = 3.5


def load_secrets():
    if not SECRETS_PATH.exists():
        sys.exit(f"Missing {SECRETS_PATH}")
    data = yaml.safe_load(SECRETS_PATH.read_text())
    missing = [k for k in ("device", "local_key", "ip") if not data.get(k)]
    if missing:
        sys.exit(f"secrets.yaml missing keys: {', '.join(missing)}")
    return data


def connect(secrets):
    dev = tinytuya.Device(
        secrets["device"],
        secrets["ip"],
        secrets["local_key"],
        version=float(secrets.get("version", DEFAULT_VERSION)),
    )
    dev.set_socketTimeout(10)
    return dev


def extract_normal_timer(data):
    if not data or not isinstance(data, dict):
        return None
    dps = data.get("dps") or {}
    return dps.get("38") or dps.get(38)


# --- Commands ---


def _record(per_zone, value, t0):
    decoded = dp38.decode_block(value)
    if not decoded or not decoded[0]:
        return
    zone, summary = decoded[0], decoded[1]
    is_new = zone not in per_zone
    per_zone[zone] = (value, summary)
    if is_new:
        print(f"  [{time.time()-t0:5.1f}s] zone {zone}: {summary}  (raw {value})")


def cmd_read(args, dev, secrets):
    t0 = time.time()
    per_zone = {}

    print(f"Querying and listening for up to {args.timeout}s "
          f"(re-nudging every {args.renudge}s)...")

    value = extract_normal_timer(dev.updatedps(["38"]))
    if value:
        _record(per_zone, value, t0)

    deadline = t0 + args.timeout
    next_nudge = time.time() + args.renudge
    dev.set_socketTimeout(2)
    while time.time() < deadline and len(per_zone) < 4:
        if time.time() >= next_nudge:
            value = extract_normal_timer(dev.updatedps(["38"]))
            if value:
                _record(per_zone, value, t0)
            next_nudge = time.time() + args.renudge
        data = dev.receive()
        value = extract_normal_timer(data)
        if value:
            _record(per_zone, value, t0)

    print()
    for z in [1, 2, 3, 4]:
        if z in per_zone:
            raw, summary = per_zone[z]
            print(f"Zone {z}: {summary}  (raw {raw})")
        else:
            print(
                f"Zone {z}: no push received within {args.timeout}s - usually "
                "means no schedule was ever written to this zone (DP 38 has no "
                "per-zone query - the device decides what to push and when, "
                "roughly every few minutes per zone that has a schedule). Try "
                "`write` on it, or rerun with a longer --timeout."
            )


def cmd_write(args, dev, secrets):
    zones = dp38.parse_zone_list(args.zones)
    block = dp38.build_block(zones, args.duration, args.times, args.cycle, args.rain)
    hex_payload = bytes(block).hex().upper()
    print(f"Sending (zones {zones}): {hex_payload}  ({dp38.block_summary(block)})")
    dev.set_value("38", hex_payload)


def cmd_clear(args, dev, secrets):
    for zone in dp38.parse_zone_list(args.zones):
        block = dp38.build_block([zone], 0, "", "all", "obey")
        hex_payload = bytes(block).hex().upper()
        print(f"Sending (zone {zone}): {hex_payload}  ({dp38.block_summary(block)})")
        dev.set_value("38", hex_payload)


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)

    p_read = sub.add_parser("read", help="Query the device and collect whichever zone blocks it pushes back")
    p_read.add_argument("--timeout", type=int, default=90, help="seconds to listen for pushes (default 90)")
    p_read.add_argument(
        "--renudge", type=int, default=10,
        help="re-send the query every N seconds while listening, in case the first "
             "nudge only prompted some zones (default 10)",
    )

    p_write = sub.add_parser("write", help="Write a schedule block for one or more zones")
    p_write.add_argument("--zones", required=True, help='e.g. "2", "1,3", or "all"')
    p_write.add_argument("--duration", type=int, required=True, help="minutes, 1-99")
    p_write.add_argument("--times", required=True, help='up to 6 comma-separated HH:MM')
    p_write.add_argument(
        "--cycle", default="days:all",
        help='"days:all" | "days:mon,wed,fri" | "odd" | "even" | "interval:N[:YYYY-MM-DD]"',
    )
    p_write.add_argument("--rain", default="obey", choices=["obey", "ignore"])

    p_clear = sub.add_parser("clear", help="Disable the schedule for one or more zones")
    p_clear.add_argument("--zones", required=True, help='e.g. "2", "1,3", or "all"')

    args = parser.parse_args()
    secrets = load_secrets()
    dev = connect(secrets)

    {"read": cmd_read, "write": cmd_write, "clear": cmd_clear}[args.command](args, dev, secrets)


if __name__ == "__main__":
    main()
