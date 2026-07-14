#!/usr/bin/env python3
"""Manual CLI to read/write the IIC-400's on-device schedule (DP 38) via the
Tuya Cloud API. Standalone - not part of the custom_components/iic400/ HA
integration, which deliberately does not manage schedules. Run by hand only.
See ts_local.py for the same tool over the local (LAN) protocol instead.

Credentials come from secrets.yaml at the repo root (gitignored):
    device: <Tuya device id>
    client: <Access ID / Client ID>
    secret: <Access Secret / Client Secret>
    region: <us | eu | cn | in>

Usage:
    python scripts/ts.py read [--days N] [--zone 1..4] [--raw]
    python scripts/ts.py write --zones 1,3 --duration 10 \
        --times 06:00,18:00 --cycle days:mon,wed,fri --rain obey
    python scripts/ts.py clear --zones 1,3

`read` note: the Tuya Cloud "current status" endpoint only ever holds ONE
cached DP 38 value (whichever zone the device last reported), same
limitation as the local protocol. But every individual report the device
has ever sent is retained in Tuya's device log (DP-report events) - in
practice the device re-reports every zone that has ever had a schedule
written to it every few minutes on its own. `read` searches that log
history and reconstructs the latest known block per zone instead of relying
on the single cached value. A zone that has never had a schedule written to
it appears to never report at all - use `write` on it once, or widen
--days, if a zone shows no data.

DP 38 byte layout and the write/read encoding quirk are documented in dp38.py.

Requires: tinytuya, pyyaml (pip install tinytuya pyyaml)
"""
import argparse
import datetime
import json
import pathlib
import sys

import tinytuya
import yaml

import dp38

SECRETS_PATH = pathlib.Path(__file__).resolve().parent.parent / "secrets.yaml"


def load_secrets():
    if not SECRETS_PATH.exists():
        sys.exit(f"Missing {SECRETS_PATH}")
    data = yaml.safe_load(SECRETS_PATH.read_text())
    missing = [k for k in ("device", "client", "secret") if not data.get(k)]
    if missing:
        sys.exit(f"secrets.yaml missing keys: {', '.join(missing)}")
    return data


def connect(secrets):
    return tinytuya.Cloud(
        apiRegion=secrets.get("region", "us"),
        apiKey=secrets["client"],
        apiSecret=secrets["secret"],
        apiDeviceID=secrets["device"],
    )


def format_time(event_time_ms):
    return datetime.datetime.fromtimestamp(int(event_time_ms) / 1000).strftime("%Y-%m-%d %H:%M:%S")


def fetch_normal_timer_log(cloud, device_id, days):
    """Query DP-report history (evtype=7) for the last `days` days and decode
    every distinct normal_timer (DP 38) entry found. Returns entries sorted
    newest-first."""
    result = cloud.getdevicelog(device_id, start=-days, evtype=7, size=100)
    if not result.get("success"):
        sys.exit(f"Cloud error: {result}")
    entries = []
    for e in result.get("result", {}).get("logs", []):
        if e.get("code") != "normal_timer":
            continue
        decoded = dp38.decode_block(e["value"])
        if decoded is None:
            continue
        zone, summary, _ = decoded
        if zone is None:
            continue
        entries.append({"time": e.get("event_time", 0), "zone": zone, "summary": summary, "raw": e["value"]})
    entries.sort(key=lambda x: x["time"], reverse=True)
    return entries


def latest_per_zone(entries):
    per_zone = {}
    for e in entries:
        per_zone.setdefault(e["zone"], e)
    return per_zone


# --- Commands ---


def cmd_read(args, cloud, secrets):
    entries = fetch_normal_timer_log(cloud, secrets["device"], args.days)

    if args.raw:
        if not entries:
            print(f"No DP 38 reports in the last {args.days} day(s).")
            return
        for e in entries:
            print(f"{format_time(e['time'])}  zone={e['zone']}  {e['summary']}  raw={e['raw']}")
        return

    per_zone = latest_per_zone(entries)
    for z in [args.zone] if args.zone else [1, 2, 3, 4]:
        e = per_zone.get(z)
        if e is None:
            print(
                f"Zone {z}: no report in the last {args.days} day(s) - the device "
                "reports each zone every few minutes on its own once a schedule "
                "has ever been written for it, so this usually means no schedule "
                "was ever written to this zone. Try `write` on it, open its "
                "schedule in the Inkbird app, or widen --days."
            )
            continue
        print(f"Zone {z}: {e['summary']}  (last reported {format_time(e['time'])}, raw {e['raw']})")


def cmd_write(args, cloud, secrets):
    zones = dp38.parse_zone_list(args.zones)
    block = dp38.build_block(zones, args.duration, args.times, args.cycle, args.rain)
    hex_payload = bytes(block).hex().upper()
    print(f"Sending (zones {zones}): {hex_payload}  ({dp38.block_summary(block)})")
    result = cloud.sendcommand(
        secrets["device"], {"commands": [{"code": "normal_timer", "value": hex_payload}]}
    )
    print(json.dumps(result, indent=2))


def cmd_clear(args, cloud, secrets):
    # One write per zone (not a combined bitmask) so clearing zone A never
    # touches zone B's schedule even though the device would happily accept
    # a combined mask - simpler to reason about for a destructive operation.
    for zone in dp38.parse_zone_list(args.zones):
        block = dp38.build_block([zone], 0, "", "all", "obey")
        hex_payload = bytes(block).hex().upper()
        print(f"Sending (zone {zone}): {hex_payload}  ({dp38.block_summary(block)})")
        result = cloud.sendcommand(
            secrets["device"], {"commands": [{"code": "normal_timer", "value": hex_payload}]}
        )
        print(json.dumps(result, indent=2))


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)

    p_read = sub.add_parser("read", help="Show each zone's last-known schedule block")
    p_read.add_argument("--days", type=int, default=7, help="lookback window in days (default 7)")
    p_read.add_argument("--zone", type=int, choices=[1, 2, 3, 4], help="show only this zone")
    p_read.add_argument(
        "--raw", action="store_true",
        help="dump every distinct DP 38 report found in the window, chronologically",
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
    cloud = connect(secrets)

    {"read": cmd_read, "write": cmd_write, "clear": cmd_clear}[args.command](args, cloud, secrets)


if __name__ == "__main__":
    main()
