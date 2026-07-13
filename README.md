# Inkbird IIC-400-WIFI — local control for Home Assistant

Local (LAN-only, no cloud dependency at runtime) integration for the
**Inkbird IIC-400-WIFI** 4-zone sprinkler/irrigation controller, built on
Tuya's local protocol.

It gives you, in Home Assistant:

- A `tuya-local` custom device profile (`inkbird_iic400_wifi.yaml`) that
  exposes the controller's simple scalar DPs as normal entities (operation
  mode, rain sensor, zones running, etc). This part is being upstreamed into
  `tuya-local`'s built-in device library — see `PR_Tuya_local/`.
- **`custom_components/iic400/`** — a real Home Assistant integration
  (installable via HACS, with a proper "Add Integration" config flow) that
  drives the two packed-binary Tuya DPs `tuya-local` can't express: DP 45
  (manual zone start/stop) and DP 38 (on-device schedules). It depends on
  `tuya-local` already being set up for the device — the config flow picks
  the existing `tuya-local` entry instead of asking you to re-enter
  credentials.

## Why two integrations for one device?

`tuya-local` is excellent at polling/pushing simple scalar DPs and is used
here for state (is a zone running? is the rain sensor blocking? what mode is
the device in?). DP 38 and DP 45 are packed binary structures (bitmasks,
multi-field byte arrays) impractical to express in `tuya-local`'s
declarative YAML DP mapping, so `custom_components/iic400/` builds and sends
those payloads directly via `tinytuya`. Both integrations talk to the device
over the same local Tuya protocol; nothing leaves your LAN at runtime.

## Repository layout

```
inkbird_iic400_wifi.yaml        tuya-local custom device profile (being upstreamed)
custom_components/iic400/       HA integration: config flow, switches, sensors, services
hacs.json                       HACS custom-repository manifest
PR_Tuya_local/                  working materials for the tuya-local upstream PR
```

---

## Prerequisites

- A running Home Assistant instance.
- [HACS](https://hacs.xyz/) installed.
- The **tuya-local** integration installed via HACS, with the IIC-400 already
  added to it (see [Step 1](#step-1--set-up-tuya-local) below) — this
  integration depends on that config entry and won't set up without it.

---

## Step 1 — Set up tuya-local

1. In HACS, search for **"Tuya Local"** (by `make-all`) and install it. If
   it isn't in the default HACS store, add it as a custom repository first:
   HACS → Integrations → ⋮ → **Custom repositories** → URL
   `https://github.com/make-all/tuya-local`, category **Integration**.
2. Until the upstream PR is merged, copy this repo's
   [`inkbird_iic400_wifi.yaml`](inkbird_iic400_wifi.yaml) into
   `/config/custom_components/tuya_local/devices/inkbird_iic400_wifi.yaml`
   (re-copy after every `tuya-local` update — HACS reinstalls the whole
   folder and wipes unmerged device files).
3. Restart Home Assistant.
4. **Settings → Devices & Services → Add Integration → Tuya Local**, using
   the local (manual) setup path with the device's ID, local key, host, and
   protocol version (get these once via the `tinytuya` wizard — see
   `tuya-local`'s own docs).
5. Confirm it's identified as **Inkbird IIC-400 irrigation controller** with
   entities including a "zones running" sensor.

---

## Step 2 — Install this integration via HACS

1. HACS → Integrations → ⋮ → **Custom repositories** → add this repo's URL,
   category **Integration**.
2. Install **"Inkbird IIC-400 Irrigation"**, then restart Home Assistant.
3. **Settings → Devices & Services → Add Integration → Inkbird IIC-400
   Irrigation**.
4. Pick your `tuya-local` device from the list (its credentials are copied
   automatically — nothing to re-type).
5. Confirm (or pick manually) the "zones running" sensor entity the config
   flow suggests — this is what zone switch state is read from.

No manual file copying, no SSH, no `pip install` — `tinytuya` is listed in
the integration's `manifest.json` and installed automatically by
HACS/Home Assistant.

You should now have, under a new **"IIC-400 Irrigation"** device:

- `switch.zone_1` … `switch.zone_4` — start/stop controls, state read from
  the real device (not assumed from our own commands).
- `number.zone_switch_failsafe_duration` — safety-net duration for the
  switches (see below).
- `sensor.zone_1_schedule` … `sensor.zone_4_schedule` — last-known on-device
  schedule per zone (passively captured, not polled).
- A shared **schedule editor** (one instance, applies to whichever zone(s) you
  name in it — not per-zone): `text.schedule_zones`,
  `text.schedule_start_times`, `number.schedule_duration`,
  `select.schedule_cycle`, `number.schedule_interval_days`,
  `switch.schedule_obey_rain_sensor`, `button.clear_schedule`,
  `button.save_schedule`, `button.refresh_schedules_from_device` (see below).
- Services `iic400.set_schedule`, `iic400.clear_schedule`,
  `iic400.quick_water` (see below).

Each entity's display name is prefixed with a two-digit number (`"01 ·
Zone 1"`, `"09 · Schedule cycle"`, `"12 · Clear schedule"`, …) purely so the
default device page's alphabetically-sorted Controls card lands in a sane
order — zone switches first, then the schedule editor fields, then the
Clear/Save/Refresh buttons last. Entity IDs are unaffected (still
`switch.zone_1`, `button.save_schedule`, etc.) — only the friendly name
shown in the UI has the prefix.

---

## Usage notes

### Zone switches — start/stop, for Smart Irrigation

`switch.zone_1..4` have no built-in duration — they're meant for automations
that time the run themselves and call `turn_off` when done, in particular
[Smart Irrigation](https://github.com/jeroenterheerdt/HAsmartirrigation)
(HACS), which calculates each zone's duration from weather data, turns the
zone's switch on, waits, then turns it off.

- `turn_on` starts the zone for `number.zone_switch_failsafe_duration`
  (default 180 min) — a safety net in case `turn_off` is ever missed (e.g. an
  HA restart mid-run), not the normal way a run ends.
- `turn_off` sends the DP 45 stop command, which **stops every manual zone
  at once** — a device firmware limitation, not a choice made here. There is
  no verified way to stop a single zone while others keep running.
- **Only run one zone at a time.** This is Smart Irrigation's default
  behavior (sequential, one zone after another) — don't configure it (or any
  automation) to run IIC-400 zones concurrently.

### Quick water — fixed duration, self-timed

Call `iic400.quick_water` (zone, duration_minutes) for a one-off manual run
that the device times and stops itself — no explicit stop needed, and it
doesn't touch the zone switches' state.

### Schedules

**Editing from the dashboard** — the shared schedule editor entities let you
write a schedule straight to the device without calling a service by hand:

1. Set `text.schedule_zones` to the target zone(s): `"2"`, `"1,3"`, or `"all"`.
2. Set `number.schedule_duration` (minutes) and `text.schedule_start_times`
   (up to 6 comma-separated `HH:MM`, e.g. `"06:30, 18:00"`).
3. Set `select.schedule_cycle` — `All days`, `Odd days`, `Even days`, or
   `Every N days` (uses `number.schedule_interval_days`, counting from
   today). Custom weekday combos (e.g. Mon/Wed/Fri) or an interval starting
   on a specific date aren't representable in the dropdown — use
   `iic400.set_schedule` below for those.
4. Toggle `switch.schedule_obey_rain_sensor` as needed.
5. Press `button.save_schedule` to write it.

Press `button.clear_schedule` at any time to disable the schedule for the
zone(s) currently in `text.schedule_zones` — it ignores the other fields.

These entities are a single shared form (not one per zone): whatever is
currently in `text.schedule_zones` is what the next Save/Clear press applies
to, so double-check it before pressing either button.

**Editing via service call** — for cycle types beyond "every day":

- `iic400.set_schedule` — `zones` (`"2"`, `"1,3"`, or `"all"`),
  `duration_minutes`, `start_times` (up to 6 comma-separated `HH:MM`),
  `cycle_type` (`all` | comma-separated weekdays e.g. `mon,wed,fri` | `odd` |
  `even` | `interval:N` or `interval:N:YYYY-MM-DD`), `rain_obey` (bool).
- `iic400.clear_schedule` — `zones` only, disables the schedule for them.
- `sensor.zone_N_schedule` reflects the last schedule block the device has
  spontaneously reported — it doesn't poll, so it may show `unknown` until
  the device pushes one (press **Refresh schedules from device** to prompt
  it).

### Rain sensor

If the tuya-local `switch.*_rain_sensor_enable` is on but no physical sensor
(or jumper) is wired to the `SENS` terminals, the device reports rain and
blocks irrigation. Turn it off if you don't have a sensor installed.

---

## Troubleshooting

| Symptom | Likely cause / fix |
|---|---|
| "Add Integration" doesn't offer Inkbird IIC-400 Irrigation | HACS install didn't complete or HA wasn't restarted after installing it. |
| Config flow aborts with "No tuya-local devices found" | Set up `tuya-local` and add the IIC-400 to it first (Step 1). |
| `switch.zone_N` stuck unavailable / wrong on-off state | The "zones running" sensor picked during setup doesn't match reality — remove and re-add this integration, and pick the correct sensor in the second config-flow step. |
| A Smart Irrigation zone cuts off mid-run | `number.zone_switch_failsafe_duration` is set lower than that zone's calculated duration — raise it. |
| Two zones' watering stops together unexpectedly | You (or an automation) started more than one zone at once — DP 45's stop halts all manual zones together by device design. Only run one zone at a time. |
| Schedule sensors stuck on `unknown` | Cache not populated yet — press **Refresh schedules from device** and retry; the device only *pushes* DP 38, it doesn't reliably answer a synchronous query. |

---

## Security notes

- Nothing here talks to Tuya's cloud at runtime.
- No local key or credentials are stored by this integration outside HA's
  own encrypted config entry storage — no more `iic400_secrets.json` file.
- Prefer reserving a static IP/DHCP lease for the device.
