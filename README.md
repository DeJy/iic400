# Inkbird IIC-400-WIFI — local control for Home Assistant

Local (LAN-only, no cloud dependency at runtime) integration for the
**Inkbird IIC-400-WIFI** 4-zone sprinkler/irrigation controller, built on
Tuya's local protocol.

It gives you, in Home Assistant:

- A `tuya-local` custom device profile that exposes the controller's
  read-only/simple DPs as normal entities (operation mode, rain sensor
  enable, master valve enable, zone sequencing, seasonal adjustment,
  zones running/pending, clock error).
- A Python script (`tinytuya`-based) that sends the two DPs `tuya-local`
  can't drive on its own — DP 45 (manual start/stop, packed binary) and
  DP 38 (on-device schedules, packed binary, 20 bytes/zone-block) — and
  caches the last-known schedule per zone to a JSON file so it can be
  displayed without opening a device connection.
- A Home Assistant **package** that wires the script into
  `shell_command`s, scripts, template zone switches (debounced against
  device state), and input helpers for building a schedule from the UI.
- A ready-to-paste **dashboard card**.

## Why two integrations for one device?

`tuya-local` is excellent at polling/pushing simple scalar DPs and is
used here for state (is a zone running? is the rain sensor blocking?
what mode is the device in?). DP 38 and DP 45 are packed binary
structures (bitmasks, multi-field byte arrays) that are impractical to
express in `tuya-local`'s declarative YAML DP mapping, so `iic400.py`
(via `tinytuya`) builds and sends those payloads directly. Both talk to
the device over the same local Tuya protocol; nothing leaves your LAN
at runtime.

## Repository layout

```
inkbird_iic400_wifi.yaml        tuya-local custom device profile
scripts/iic400.py               control script (start/stop/schedule), needs tinytuya
packages/iic400_package.yaml    HA package: shell_command, scripts, switches, sensors, helpers
dashboard/iic400_dashboard_card.yaml   Lovelace manual card (paste into a dashboard)
```

---

## Prerequisites

- A running Home Assistant instance (OS, Supervised, Container, or Core
  — all work; see the Python install notes below for the difference).
- [HACS](https://hacs.xyz/) installed, for the `tuya-local` integration.
- File access to `/config` (Studio Code Server / File editor add-on,
  Samba, or SSH — any of these is fine).
- The IIC-400 already paired and working in the **Tuya Smart** or
  **Smart Life** app, on the same network/VLAN as Home Assistant.
- A free [Tuya IoT Platform](https://iot.tuya.com/) developer account,
  used **once** to read the device's local encryption key. This does
  **not** create an ongoing cloud dependency — after this step Home
  Assistant talks to the device only over the LAN.

---

## Step 1 — Get the device's local credentials

`tuya-local` and `iic400.py` both need: **Device ID**, **Local Key**,
**IP address**, and **protocol version**. The easiest way to get all
four at once is the `tinytuya` setup wizard.

1. On any machine with Python (your laptop is fine, it doesn't need to
   be the HA host), install `tinytuya`:
   ```bash
   python3 -m pip install tinytuya
   ```
2. Create a free account at [iot.tuya.com](https://iot.tuya.com/) and:
   - Create a **Cloud Project** (any subscription tier that includes
     "IoT Core" — the free trial is enough).
   - Under **Devices → Link Tuya App Account**, link the same
     Tuya Smart / Smart Life account you used to pair the IIC-400.
   - Note the **Access ID** and **Access Secret** from the project
     overview page.
3. Run the wizard and follow the prompts (region, Access ID/Secret,
   then your app account's login email/password used for linking):
   ```bash
   python3 -m tinytuya wizard
   ```
   This produces `devices.json` in the current directory, listing every
   linked device with its `id`, `key` (local key), `ip`, and
   `version`. Find the IIC-400 entry (product id `x7hkmeis8yqj6ntj`) and
   keep these four values — you'll need them twice (tuya-local setup,
   and the script's credentials file).

   > The **IoT Core** subscription trial expires after ~1 month. That's
   > fine — you only need cloud access for this one-time key retrieval.
   > If the key ever changes (e.g. you re-pair the device in the app),
   > re-run the wizard.

4. Confirm the device's static/reserved IP in your router/DHCP server
   so it doesn't change later — both `tuya-local` and `iic400.py` are
   configured with a fixed IP.

---

## Step 2 — Install `tuya-local` and the custom device profile

1. In HACS, search for **"Tuya Local"** (by `make-all`) and install it.
   If it doesn't show up in the default HACS store, add it as a custom
   repository first: HACS → Integrations → ⋮ menu → **Custom
   repositories** → URL `https://github.com/make-all/tuya-local`,
   category **Integration**.
2. Copy this repo's [`inkbird_iic400_wifi.yaml`](inkbird_iic400_wifi.yaml)
   into:
   ```
   /config/custom_components/tuya_local/devices/inkbird_iic400_wifi.yaml
   ```
   The IIC-400 isn't in `tuya-local`'s built-in device library, so
   without this file the integration won't recognize it (or will only
   expose a handful of generic DPs).

   > **Update caveat:** HACS reinstalls the whole `tuya-local` folder on
   > update, which will delete this custom file. After every `tuya-local`
   > update, re-copy `inkbird_iic400_wifi.yaml` into `devices/` before
   > restarting Home Assistant, or the integration will fail to
   > recognize the device on the next config reload.

3. **Restart Home Assistant** (required for both HACS and the new
   device profile to be picked up).
4. Go to **Settings → Devices & Services → Add Integration → Tuya
   Local**. Choose the **local (manual) setup path** (skip cloud
   linking here — you already have the key), and enter:
   - Device ID
   - Local key
   - Host/IP address
   - Protocol version (from the wizard output; if unsure, try `3.5`,
     then `3.4`/`3.3`, or use `auto`)
5. It should be identified as **Inkbird IIC-400 irrigation controller**.
   Complete setup and confirm you get entities including:
   - `select.inkbird_iic_400_irrigation_controller_operation_mode`
   - `switch.inkbird_iic_400_irrigation_controller_rain_sensor_enable`
   - `sensor.inkbird_iic_400_irrigation_controller_zones_running_raw`
     — **this exact entity is required** by the package in Step 5.

   (Exact entity IDs depend on the device name you give it during
   setup; if you rename the device, update the entity references in
   `packages/iic400_package.yaml` to match.)

---

## Step 3 — Install Python dependencies for the control script

`iic400.py` needs the `tinytuya` package importable by the **same
Python interpreter Home Assistant Core runs under** (that's what
`shell_command` will invoke). How you get a shell depends on your
install type:

- **Home Assistant OS / Supervised**: install the official **Terminal &
  SSH** add-on (Settings → Add-ons → Add-on Store), open its terminal,
  then run:
  ```bash
  python3 -m pip install tinytuya --target /config/scripts/lib
  ```
  (`--target` installs into a folder alongside the script instead of
  the system site-packages, since HA OS's Core container is otherwise
  read-only/unmanaged for pip.)
- **Home Assistant Container / Docker**: run pip inside the running
  container so it lands where Core's Python will find it:
  ```bash
  docker exec -it homeassistant python3 -m pip install tinytuya --target /config/scripts/lib
  ```
  (replace `homeassistant` with your container name if different).
- **Home Assistant Core (venv install)**: activate the same venv HA
  runs under, then:
  ```bash
  pip install tinytuya --target /config/scripts/lib
  ```

`iic400.py` already does `sys.path.insert(0, "/config/scripts/lib")`
before `import tinytuya`, so a `--target` install is picked up
automatically — no environment variables to set.

Verify it worked:
```bash
python3 -c "import sys; sys.path.insert(0, '/config/scripts/lib'); import tinytuya; print(tinytuya.__version__)"
```

---

## Step 4 — Deploy the script and its credentials

1. Copy [`scripts/iic400.py`](scripts/iic400.py) to `/config/scripts/iic400.py`.
2. Give it device credentials, either of:
   - **Automatic (recommended):** do nothing. The script reads
     `device_id`, `local_key`, `host`, and `protocol_version` straight
     out of `/config/.storage/core.config_entries` for whichever
     `tuya_local` entry's title contains `"iic"` (case-insensitive) —
     i.e. the entry you created in Step 2. This keeps a single source
     of truth: if you later re-pair the device and reconfigure it in
     `tuya-local`, the script picks up the new key automatically.
   - **Manual override:** create `/config/scripts/iic400_secrets.json`
     (already excluded via [`.gitignore`](.gitignore) — **never commit
     it**):
     ```json
     {
       "device_id": "your_device_id",
       "device_ip": "192.168.x.x",
       "local_key": "your_local_key",
       "version": 3.5
     }
     ```
     Use this if the device isn't in `tuya-local` yet, or you want the
     script independent of the integration's stored config.
3. Sanity-check from the HA host shell:
   ```bash
   python3 /config/scripts/iic400.py status
   ```
   You should get a dict dump of the device's current DPs, not an
   exception. If it fails with a credentials error, re-check Step 1's
   values; if it times out, check the device's IP/VLAN/firewall.

---

## Step 5 — Install the Home Assistant package

1. In `configuration.yaml`, make sure packages are enabled:
   ```yaml
   homeassistant:
     packages: !include_dir_named packages
   ```
2. Copy [`packages/iic400_package.yaml`](packages/iic400_package.yaml)
   to `/config/packages/iic400.yaml`.
3. **Check → Restart** (Developer Tools → YAML → Check Configuration,
   then Settings → System → Restart, or just restart directly).
4. After restart you should have, among others:
   - `input_number.iic400_manual_minutes`, `input_number.iic400_minutes`
   - `input_text.iic400_zones`, `input_text.iic400_times`, `input_text.iic400_mode`
   - `input_select.iic400_rain`
   - `switch.zone_1` … `switch.zone_4` (template switches — state
     reflects the device's actual reported zone status via DP 107,
     debounced by ~4s on / ~2s off to ignore transient reconnect
     glitches; turning one on calls `iic400.py start`, off calls
     `iic400.py stop`)
   - `sensor.zone_1_schedule` … `sensor.zone_4_schedule`
   - `script.water_zone`, `script.stop_watering`,
     `script.iic400_apply_schedule`, `script.iic400_clear_schedule`,
     `script.iic400_refresh_schedules`
   - `sensor.iic400_schedules` (reads the JSON cache the script writes;
     empty/`unknown` until you run the refresh script once — see Step 7)

   If `switch.zone_1`–`4` show `unavailable`/template errors, the
   template's `sensor.inkbird_iic_400_irrigation_controller_zones_running_raw`
   reference doesn't match your actual entity ID from Step 2 — open
   `packages/iic400_package.yaml` and fix the four `state:` templates
   under `binary_sensor:` to your real entity ID.

---

## Step 6 — Add the dashboard card

1. Open the dashboard where you want irrigation controls, click **Edit
   Dashboard → Add Card → Manual** (bottom of the card picker).
2. Paste the contents of
   [`dashboard/iic400_dashboard_card.yaml`](dashboard/iic400_dashboard_card.yaml)
   and save.

You get three sections: manual watering (zone on/off + duration),
on-device schedules (read-only summary per zone, plus a re-read
button), and a schedule editor (zones/duration/times/mode/rain →
Apply or Clear).

---

## Step 7 — First run: pull the existing schedules

The schedule summaries shown on the dashboard come from a local JSON
cache (`/config/scripts/iic400_schedules.json`), not a live device
call, so it starts out empty. Populate it once:

- From the dashboard, click **"Re-read from device"**, or
- From a shell: `python3 /config/scripts/iic400.py schedules`

This listens passively for the device to report DP 38 (all 4 zone
blocks); it may take a couple of retries (the script retries 3× with a
6s window each) to catch all 4. Re-run if any zone still shows
`unknown`.

---

## Usage notes

- **Manual watering**: set `input_number.iic400_manual_minutes`, then
  toggle a `switch.zone_N` on. Toggling it off (or any means of manual
  stop) sends the DP 45 stop command, which ends the *entire* manual
  run, not just that zone — this mirrors how the device firmware
  handles DP 45.
- **Schedules**: fill in `input_text.iic400_zones` (`"2"`, `"1,3"`, or
  `"all"`), `input_number.iic400_minutes`, `input_text.iic400_times`
  (up to 6 comma-separated `HH:MM`), `input_text.iic400_mode`
  (`all` | comma-separated weekdays e.g. `mon,wed,fri` | `odd` | `even`
  | `interval:N` or `interval:N:YYYY-MM-DD`), and
  `input_select.iic400_rain` (`obey`/`ignore`), then run **Apply**.
  **Clear** disables the schedule for the zones currently entered in
  `input_text.iic400_zones`.
- **Rain sensor**: if `switch.*_rain_sensor_enable` is on but no
  physical sensor (or jumper) is wired to the `SENS` terminals, the
  device reports rain and blocks irrigation (blinking rain indicator
  on the unit). Turn the switch off if you don't have a sensor
  installed.
- The device's internal schedule clock is normally kept in sync by the
  Inkbird app; without ever opening that app it free-runs and can
  drift, independent of this integration.

---

## Troubleshooting

| Symptom | Likely cause / fix |
|---|---|
| `Credentials not found` from `iic400.py` | Neither `iic400_secrets.json` exists nor a `tuya_local` entry with `"iic"` in its title is found in `core.config_entries`. Create the secrets file or check the device's title in tuya-local. |
| `iic400.py` times out / connection refused | Wrong/stale IP (reserve a static DHCP lease), device on a different VLAN/isolated Wi-Fi, or a firewall blocking the local Tuya port (6668/6669). |
| Decryption / auth errors from tinytuya | Local key is stale — it changes if you unpair/re-pair the device in the Tuya/Smart Life app. Re-run the wizard (Step 1) and update `iic400_secrets.json` or reconfigure the `tuya-local` entry. |
| `switch.zone_N` stuck `unavailable` | The zones-running-raw sensor entity ID in `packages/iic400_package.yaml` doesn't match your actual `tuya-local` entity ID — fix the four `binary_sensor.state` templates. |
| Zone switch flickers on/off around start/stop | Expected transiently — the template's debounce (`delay_on: 4s`, `delay_off: 2s`) is there specifically to smooth over `tuya-local` reconnect blips after a `shell_command`. If it persists beyond a few seconds, check Wi-Fi signal to the device. |
| Custom device profile "disappears" after a `tuya-local` update | HACS replaces the whole integration folder on update, wiping unmerged files under `custom_components/tuya_local/devices/`. Re-copy `inkbird_iic400_wifi.yaml` after every `tuya-local` update (see Step 2 note). |
| `shell_command` does nothing / silently fails | Check **Settings → System → Logs** for the `shell_command` domain; a nonzero exit isn't surfaced in the UI. Run the same `python3 /config/scripts/iic400.py ...` command manually from the HA host's shell to see the real error. |
| Schedule sensors stuck on `unknown` | Cache file not populated yet — run **"Re-read from device"** (Step 7) and retry if fewer than 4/4 blocks were received. |

---

## Security notes

- `iic400_secrets.json` and `iic400_schedules.json` are already listed
  in [`.gitignore`](.gitignore) — never commit them (the local key
  grants full local control of the device).
- Nothing here talks to Tuya's cloud at runtime; the IoT Platform
  account from Step 1 is only used offline, once, to read the key.
- Prefer reserving a static IP/DHCP lease for the device over hardcoding
  a dynamic one, and keep it on a network segment Home Assistant can
  reach without routing changes.
