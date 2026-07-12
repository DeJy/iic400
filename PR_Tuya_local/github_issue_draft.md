## Title

Add support for Inkbird IIC-400-WIFI 4-zone irrigation controller

## Device info

- Brand: Inkbird
- Model: IIC-400-WIFI
- Product ID: `x7hkmeis8yqj6ntj`
- Integration: `tuya_local` 2026.7.1
- Protocol version: 3.5 (tinytuya 1.20.0)
- Proposed device config: `inkbird_iic400_wifi.yaml` (https://github.com/DeJy/iic400/blob/master/inkbird_iic400_wifi.yaml)

This device exposes two packed-binary DPs (38 for on-device schedules, 45 for
manual zone start/stop) that don't map cleanly onto `tuya-local`'s scalar DP
schema, so I'm requesting it be added as a custom device type rather than
expressed purely through the declarative YAML DP mapping.

## Match quality (config flow)

Captured on a clean remove + re-add of the integration entry (not a reload):

```
2026-07-12 10:55:42.810 WARNING (MainThread) [custom_components.tuya_local.config_flow] Device matches inkbird_iic400_wifi with quality of 73%. LOCAL DPS: {"updated_at": 1783868139.8972127, "38": "0400FFFFFFFFFFFFFFFFFFFFFFFF007F00000011", "44": "order", "101": "Auto", "102": true, "103": 0, "104": 268697671, "106": false, "107": 0, "108": 0, "110": false, "111": true}
2026-07-12 10:55:42.810 WARNING (MainThread) [custom_components.tuya_local.config_flow] Include the previous log messages with any new device request to https://github.com/make-all/tuya-local/issues/
```

Note on the <100% score: DPs 104, 105 and 110 are intentionally left unmapped
in the device config — they are not user-facing state:
- **DP 104** — internal history/log pointer (large monotonically-changing
  integer, no useful representation as an HA entity)
- **DP 105** — factory reset trigger
- **DP 110** — OTA update-in-progress flag (device must not be power-cycled
  while set)

## Steady-state DPS (full poll)

```
2026-07-12 10:46:21.399 DEBUG (MainThread) [custom_components.tuya_local.device] Inkbird IIC-400 irrigation controller received {"38": "0400FFFFFFFFFFFFFFFFFFFFFFFF007F00000011", "44": "order", "101": "Auto", "102": true, "103": 0, "104": 268697671, "106": false, "107": 0, "108": 0, "110": false, "111": true, "full_poll": true}
```

## DP 45 — manual zone start/stop (all 4 zones exercised individually)

Captured while switching to Manual mode and starting each zone in turn from
the device's own controls, then returning to Auto:

```
Zone 1 start: {"45": "AAEACgAAAAAAAAAAAAAAAAAA", "full_poll": false}
Zone 2 start: {"45": "AAEAAAAKAAAAAAAAAAAAAAAA", "full_poll": false}
Zone 3 start: {"45": "AAEAAAAAAAoAAAAAAAAAAAAA", "full_poll": false}
Zone 4 start: {"45": "AAEAAAAAAAAACgAAAAAAAAAA", "full_poll": false}
Stop:         {"45": "AAEAAAAAAAAAAAAAAAAAAAAA", "full_poll": false}
```

These confirm the documented layout: `[0]=1` start flag, `[1]=1` zone-specific
flag, then 2-byte-BE run-time slots per zone (z1..z4), each zone's 10-minute
run time shifting two bytes further along the payload as the zone index
increases. Stop is `[0]=1` with everything else zero (stops all manual
watering, not a single zone — this matches the device firmware, not a bug in
the config).

## DP 38 — schedule block, byte [0] varies by zone

Captured while browsing zone schedules in the app / editor:

```
{"38": "010A0BFFFFFFFFFF02FFFFFFFFFF007F00000011", "full_poll": false}   (zone 1, 10 min duration configured, one start time set)
{"38": "0200FFFFFFFFFFFFFFFFFFFFFFFF007F00000011", "full_poll": false}   (zone 2, no schedule configured — duration 0)
{"38": "0300FFFFFFFFFFFFFFFFFFFFFFFF007F00000011", "full_poll": false}   (no schedule configured)
{"38": "0400FFFFFFFFFFFFFFFFFFFFFFFF007F00000011", "full_poll": true}    (steady-state / idle value seen throughout normal operation)
```

## Diagnostics export

Attached: `config_entry-tuya_local-01KX9GQ10HX0D0KNEKG2VXEZC4.json`
(device_id, local_key and host already redacted by Home Assistant's own
diagnostics export — nothing further removed).

## Proposed device config

See `inkbird_iic400_wifi.yaml` in this repo:
https://github.com/DeJy/iic400/blob/master/inkbird_iic400_wifi.yaml
