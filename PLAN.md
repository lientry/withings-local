# Withings scale → local data → Home Assistant

Goal: read measurements from a Withings scale without the Withings cloud, then expose them in Home Assistant through a local integration.

## Why BLE, not Wi-Fi

| Route | How it works | Status on current scales |
|---|---|---|
| **Wi-Fi interception** | DNS-redirect the scale's cloud host to a local server that emulates it | Worked on old plain-HTTP models (WBS01, WS-30, WS-50). The Body (WBS06) uses mutual TLS with a per-device key, so a fake server can't impersonate the cloud. Assume newer models are similar until proven otherwise. |
| **BLE ("WPP" protocol)** | Act like the Health Mate app: connect over BLE, authenticate, pull stored measurements | Demonstrated publicly for Body+ (WBS05) and Body Smart (WBS13). The same framing is used across Withings devices (Steel HR, ScanWatch), so other scales very likely work too. |

**Plan of record: BLE.** Wi-Fi stays a branch only if the scale turns out to be an old plain-HTTP model.

What prior work says about WPP (from research — still to be verified against *your* scale):
- **UUIDs:** `000000XX-5749-5448-MMMM-000000000000`, where `5749-5448` is ASCII "WITH" and MMMM is the model ID. The scale uses service `0x20` and one write/notify characteristic `0x24`.
- **Framing:** `01 | cmd u16 BE | len u16 BE | TLVs (type u16, len u16, value)`.
- **Auth:**
  - BLE bonding is Just Works on the Body+; the Body Smart shows a passkey on its display.
  - The app then answers a challenge with `SHA1(challenge ‖ mac_lower ‖ kl)`.
  - `kl` is a per-scale secret created at association time. It can be fetched once from Withings' legacy account API.
- **Session flow:**
  1. PROBE (257)
  2. PROBE_CHALLENGE (296)
  3. TIME_SET (1281)
  4. STORED_MEASURE (271)
  5. SYNC_OK (277)

  Measurement type codes match the public Withings API (1 = weight, 8 = fat mass, …).
- **References:**
  - openwithings (Body+, Python/bleak)
  - Gadgetbridge `withingssteelhr` (Java)
  - withouthings `tools/wpp.json` (a full command table extracted from Health Mate)
  - esphome-withings-wpp (Body Smart) — **PolyForm Noncommercial license**, so we read its docs but write our own code.

## Target: Body Smart (WBS13)

- **Model ID:** WPP model id `0x0010` (to confirm with the scan).
- **Advertising:** about 55 s after every weigh-in, even when the scale is in Wi-Fi mode. That gives the HA integration a natural trigger.
- **Pairing:** BLE pairing uses a 6-digit passkey shown on the scale's display. On macOS, CoreBluetooth shows the system pairing dialog. In HA, passkey pairing through a local adapter works; through an ESPHome proxy it is unverified.
- **MAC address:** macOS hides real MAC addresses from bleak, but the identity MAC is in the service-UUID tail, and the auth challenge needs exactly that.
- **Closest reference:** esphome-withings-wpp (Body Smart). Read only; it's non-commercial licensed.
- **Phone:** the Withings app runs on an Android phone.
- **Key experiment (phase 5):** does a local GETALL + SYNC_OK stop the scale's own Wi-Fi upload to Withings? If it does, choose between local-only and pulling without acknowledging.

## Status (2026-10-16)

| Phase | State |
|---|---|
| 0–2 Target, tooling, recon | **done**: advertisement, GATT layout and probe documented in `docs/` |
| 3 Protocol from the app | **done**: session flow, records and advertisement in `docs/protocol.md` |
| 4 Ground truth | **done differently**: checked against the real scale instead of HCI captures. The app still received a reading we had already read (16:29), because we never delete. Value-by-value comparison is pending. |
| 5 Library | **working**: codec, mutual auth, read-only client, `tools/read_measurements.py`. Still missing: multi-user mapping, TIME_SET, packaging. |
| 6 HA integration | next |

Decided along the way:
- The scale runs in **Bluetooth mode**. In Wi-Fi mode it has no BLE trigger.
- `kl` comes from the user's own account (`tools/fetch_kl.py`).
- The phone app deletes readings after it uploads them, so "first reader wins" (see `docs/recon.md`).

## Phases

### 0. Identify the target — done
Body Smart (WBS13). Firmware version still to note (Health Mate → Devices → Body Smart).

### 1. Tooling (macOS)
- Install with `brew`:
  - `android-platform-tools` (adb)
  - `jadx`
  - `apktool`
  - `wireshark` (tshark/capinfos)
  - Optionally `mitmproxy` (only for the Wi-Fi branch) and Ghidra (only if native libraries matter).
- Wire them into rea and re-run `rea doctor`. rea's jadx provider needs a separate `jadx-headless-mcp` JAR (`REA_JADX_MCP_JAR`); until then the plain `jadx` CLI does the decompiling.
- Bluetooth scripts must run from **your own Terminal**: macOS aborts processes without Bluetooth permission, and the Claude app doesn't have it.

### 2. Recon (no secrets needed)
- `uv run tools/ble_scan.py 60` while stepping on the scale. This confirms:
  - the WITH service UUID and model ID
  - the identity MAC
  - the advertising window
- GATT inventory: connect and list services and characteristics. No auth needed yet.
- Wi-Fi side (optional): the router's DNS log shows which hostnames the scale calls and whether it uses TLS.

### 3. Protocol extraction from Health Mate
- Get the APK (`com.withings.wiscale2`) from your phone with `adb shell pm path` and `adb pull`, so it comes from a trusted source.
- Decompile it with jadx and rea. The target package is `com.withings.comm.wpp.generated`, which holds the command IDs, object (TLV) IDs, field layouts and the scale model IDs.
- Output: `docs/wpp-commands.json` and `docs/protocol.md` for your model, cross-checked against withouthings' `wpp.json`.

### 4. Ground-truth capture
- Android: Developer options → *Enable Bluetooth HCI snoop log*, run a Health Mate sync, then grab the log from a bug report (rea `collect_adb_bugreport`).
- Decode it with tshark and line each frame up against the spec from phase 3:
  - auth exchange
  - TIME_SET
  - the measurement records
  - SYNC_OK
- These frames become test fixtures.

### 5. `withings_wpp` Python library (clean-room, MIT)
- **Codec:** frame/TLV encoder and decoder, with round-trip tests built from the captured frames.
- **Client (bleak + `bleak-retry-connector`):**
  - connect and bond
  - PROBE and challenge
  - TIME_SET
  - GETSTATE / GETALL
  - SYNC_OK
- **Measurements:** decoded into typed records (timestamp, user, weight, fat %, muscle, bone, hydration, heart rate, …).
- **`kl` provisioning:** a one-time script that *you* run with your Withings credentials (I won't handle the password). It stores `kl` locally.
- **Coexistence decision:**
  - Acknowledging a sync (and never sending DELALL) may stop Health Mate from receiving those readings.
  - Decide between local-only and both. To keep both, leave the scale in Wi-Fi mode if the model still advertises after a weigh-in (the Body Smart does; the Body+ doesn't).
- **CLI:** `withings-wpp dump` prints new measurements. Exit: it matches Health Mate's values for several weigh-ins.

### 6. Home Assistant integration `withings_local` — next
- **Manifest:**
  - `bluetooth` matcher on the WITH service-UUID pattern, or on the local name
  - `iot_class: local_push`
  - requirement: `withings_wpp`
- **Config flow:** Bluetooth discovery → confirm → `kl` (paste it, or run the fetch helper once) → user mapping.
- **Runtime:**
  - An advertisement (the scale wakes on weigh-in) triggers an active connection through `ActiveBluetoothDataUpdateCoordinator`.
  - It works through local adapters and ESPHome Bluetooth proxies. Proxies need pairing support; passkey pairing through a proxy is still to be verified.
- **Entities:** per Withings user, one sensor per measurement type, with correct units and device classes and `state_class: measurement`, as `RestoreSensor` so values survive restarts. Plus last-sync and battery diagnostics.
- **Multi-user:** map the scale's user slots to HA people/devices.
- **Tests:** `pytest-homeassistant-custom-component` with mocked BLE using the fixtures from phase 4. Manual test on a dev HA instance in Docker.
- **Ship:** HACS repo first. Upstreaming to HA core is possible later because the library is clean-room and MIT.

### 7. Branch: plain-HTTP Wi-Fi models only
Run a local `scalews.withings.net` emulator with a DNS override and the `/cgi-bin/*` endpoints from the ws30 / ScaleWS docs. Feed HA through a local webhook or MQTT.

## Publishing rules (this repo goes public)

The project is built to be shared on GitHub. The legal basis is reverse engineering for interoperability (EU 2009/24/EC Art. 6; US fair use and DMCA §1201(f)). These rules keep it on that footing:

1. **Clean-room output only.** Never commit Withings material:
   - APKs, decompiled sources or jadx output
   - firmware
   - copied tables or strings from the app

   Protocol facts go in `docs/` in our own words, and the code is written from those docs.
2. **No copied code from references.** esphome-withings-wpp (PolyForm Noncommercial) and Gadgetbridge (AGPL) are read for understanding only. Our code is MIT.
3. **No secrets or personal data:**
   - `kl` keys, MAC addresses, account tokens and passwords
   - raw BLE/HCI captures and bug reports
   - real measurements

   All of these live in the git-ignored folders `secrets/`, `captures/` and `work/`. Test fixtures are synthesized or redacted (MAC, `kl`, timestamps, values) before they go into `tests/fixtures/`.
4. **Trademark:** use "Withings" only to name the compatible hardware. No logos, and keep the "not affiliated" notice in the README.
5. **The `kl` fetch helper is optional and separate.** It uses the user's own account against Withings' legacy API, documented as such. Look into getting the key from the phone as an alternative.
6. **Before each push:** check `git status` and `git diff --cached` for anything under rule 1 or 3.

## Open risks
- `kl` depends on the legacy account API still working. If it stops, fall back to extracting it from the phone (Frida on rooted Android, or app storage).
- Body+ mixes Classic Bluetooth/SPP with BLE. macOS and BlueZ may need an LE-only connection.
- Pulling data via BLE can take readings away from Health Mate (see the coexistence decision).
- Firmware updates can change the protocol. Keep fixtures and re-run them after each update.
