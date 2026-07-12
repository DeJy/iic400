# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this repo is

A Home Assistant integration for the **Inkbird IIC-400-WIFI** 4-zone irrigation
controller, built on Tuya's local (LAN-only) protocol. Two parts:

1. `inkbird_iic400_wifi.yaml` — a `tuya-local` custom device profile for the
   simple scalar DPs, being upstreamed into `tuya-local`'s built-in device
   library (see `PR_Tuya_local/`). Copy-paste into `/config` until merged.
2. `custom_components/iic400/` — a real Home Assistant integration (Python,
   HACS-installable, config-flow-based) for the two packed-binary DPs
   `tuya-local` can't express: DP 45 (manual start/stop) and DP 38
   (on-device schedules). This is the part with actual code and logic; treat
   it like a normal HA custom_component, not a config-only repo.

There is no test suite for `custom_components/iic400/` beyond manual/hardware
verification — "testing" a DP-layout change means reasoning carefully about
the byte layout and, where possible, checking `tuya_dp.py`'s pure functions
against captured device traces with a standalone `python3` script (no HA
needed for that part).

## Repository layout

- [`inkbird_iic400_wifi.yaml`](inkbird_iic400_wifi.yaml) — `tuya-local`
  device profile. Deploys to
  `/config/custom_components/tuya_local/devices/`. Out of scope for most
  changes here — see `PR_Tuya_local/` for the upstream effort.
- [`custom_components/iic400/`](custom_components/iic400/) — the HA
  integration:
  - `tuya_dp.py` — pure DP 38/DP 45 byte-packing (no I/O, no HA imports).
  - `tuya_client.py` — thin sync wrapper around `tinytuya`; every method is
    blocking and must be called via `hass.async_add_executor_job`.
  - `coordinator.py` — `DataUpdateCoordinator` with a long-lived background
    listener task (DP 38 is pushed by the device, not polled).
  - `config_flow.py` — picks an existing `tuya_local` config entry (no
    manual credential re-entry) and resolves its "zones running" sensor via
    the entity registry.
  - `switch.py`, `number.py`, `sensor.py`, `button.py` — entity platforms.
  - `services.yaml` + handlers in `__init__.py` — `set_schedule`,
    `clear_schedule`, `quick_water`.
- [`hacs.json`](hacs.json) — HACS custom-repository manifest for
  `custom_components/iic400/`.
- [`PR_Tuya_local/`](PR_Tuya_local/) — working materials for upstreaming
  `inkbird_iic400_wifi.yaml`: a draft GitHub issue with captured DP
  logs/match-quality output, and a redacted HA diagnostics export. Scratch
  space for that PR, not part of the runtime integration.

## Architecture: two integrations, one device

`tuya-local` polls/pushes simple scalar DPs declaratively (device state:
mode, rain sensor, zones running bitmask). DP 38 and DP 45 are packed binary
structures impractical to express in `tuya-local`'s YAML DP mapping, so
`custom_components/iic400/` builds and sends those payloads directly via
`tinytuya`. Both talk to the same device over the same local Tuya protocol;
nothing leaves the LAN at runtime. This integration **depends on**
`tuya-local` (see `manifest.json`'s `dependencies`) both for HA's setup
ordering and because its config flow reads an existing `tuya_local` config
entry's credentials rather than asking the user to re-enter them.

**Deliberately separate device registry entry**: this integration's entities
get their own HA "device" card rather than attaching to `tuya-local`'s
device. Merging them would require depending on `tuya-local`'s internal
device-identifier format, which isn't a stable public API — a lesson from
the previous script-based design, which read `tuya-local`'s config entry
straight off `/config/.storage/core.config_entries` and explicitly noted
that could break between HA versions. The current design avoids that
category of fragility by using `hass.config_entries.async_entries(...)`
(the live API) for credentials, and a user-confirmed entity-registry lookup
(with manual override) for the zones-running sensor, rather than guessing
either from disk or from a hardcoded string.

### Protocol details

Full DP 38 / DP 45 byte layouts are documented in the docstring at the top
of [`custom_components/iic400/tuya_dp.py`](custom_components/iic400/tuya_dp.py).
Key points:

- DP 38 (schedules) is 20 bytes per zone block: zone bitmask, duration,
  6 start-time slots (hour/minute arrays), a cycle type (custom days / odd
  / even / interval), and a rain-obey flag. One write per invocation. It is
  **pushed by the device**, not reliably answerable via a synchronous query
  — the coordinator keeps a background listener running rather than polling.
- DP 45 (manual run) is 18 bytes, base64-encoded, start/stop for zones. The
  layout in `tuya_dp.py` is hardware-confirmed (2026-07-12): sending it
  flips DP 101 (operation mode) to `"Manual"` on its own and sets the
  corresponding DP 107 zone bit. An alternate layout hypothesized from a
  differently-captured trace was tested back-to-back on the same device and
  did not start the zone or flip the mode - rejected, no open discrepancy.
  Note DP 101 is apparently not independently settable as a way to "arm"
  manual mode (writing `"Manual"` to it directly, with no DP 45 write,
  reverts to `"Auto"` on its own) - it's a side effect of a valid DP 45
  write, not a precondition to set separately.
- Stopping (`build_stop`) halts **all** manual zones at once, not a single
  zone — confirmed hardware behavior. `switch.py` relies on this and
  documents it loudly; do not build a "recompute remaining time and reissue
  DP 45 for the other running zones" workaround without testing it against
  real hardware first.
- DP 104 (history log pointer), DP 105 (factory reset trigger), and DP 110
  (OTA-in-progress flag) are intentionally left unmapped in the tuya-local
  device profile — not user-facing state, and DP 110 in particular must not
  be acted on (device shouldn't be power-cycled while it's set).
- The device's internal schedule clock is normally kept in sync by the
  Inkbird app; without it, it free-runs.

### Smart Irrigation compatibility (design decision, 2026-07)

`switch.zone_1..4` are deliberately plain start/stop controls (no built-in
duration) so they work as the per-zone `switch` entity in HA's Smart
Irrigation integration, which turns a zone on, waits its own calculated
duration, then turns it off itself — it never passes a duration into
`turn_on`. `turn_on` starts the zone for
`number.zone_switch_failsafe_duration` (default 180 min) purely as a safety
net; the real stop is the caller's own `turn_off`. This assumes
**sequential-only** zone operation (only one zone running at a time) — see
the stop-all-zones note above for why running zones concurrently isn't
supported.

### Entity state tracking

Zone switch `is_on` is derived from `tuya-local`'s "zones running" sensor
(subscribed via `async_track_state_change_event`, debounced with
`async_call_later` per `const.ZONE_STATE_DELAY_ON/OFF` to smooth over
`tuya-local` reconnect blips right after a DP write) — **not** from locally
tracking "did we just send a start/stop command." This keeps state correct
if a zone is stopped by the physical device buttons, the Inkbird app, a
rain-sensor skip, or a fault. Don't replace this with local optimistic
tracking even though it would look simpler.

## Making changes

- If you touch the DP 38/DP 45 byte layout, it lives in exactly one place
  now: `custom_components/iic400/tuya_dp.py` (pure functions, no I/O) — no
  mirrored copy to keep in sync elsewhere.
- `custom_components/iic400/` is a real HA custom_component: `manifest.json`
  requirements (`tinytuya`) are auto-installed by HACS/HA — don't reintroduce
  a manual `pip install --target` step or a `sys.path.insert` hack.
- `inkbird_iic400_wifi.yaml` is written with an eye toward being merged
  upstream into `make-all/tuya-local`'s built-in device library (see
  `PR_Tuya_local/github_issue_draft.md`) — keep entity names plain English
  and avoid repo-specific assumptions that wouldn't make sense as a
  general-purpose device profile. This file and `custom_components/iic400/`
  are otherwise independent; don't couple them beyond the DP 107 sensor
  lookup already described above.
