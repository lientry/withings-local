# Recon log

Observations from our own scale (Body Smart, WBS13, in Wi-Fi mode). Raw scans stay in git-ignored `captures/`. This file only records conclusions, with no addresses or neighbouring devices.

## 2026-10-16 — BLE advertisement scans (macOS, CoreBluetooth via bleak)

| Scan | Trigger | Result |
|---|---|---|
| 90 s | none (scale idle) | no Withings advertisement |
| 90 s | user stepped on the scale | no Withings advertisement; no new strong (> −75 dBm) advertiser |
| 120 s | short press of the button under the scale | no Withings advertisement; two new, empty advertisements at about −78 dBm (no name, UUIDs or manufacturer data), not identified |

Each scan matched on "WITH" service UUIDs (`-5749-5448-`) and on names containing withings/wbs/body/scale.

Range was not the problem: the scale was about 1 m from the Mac.

### Timed scan: found it

To tell the scale apart from background devices, the scan first spent 30 s learning the background, then the user short-pressed the button. The scale showed a QR code reading "open withings app", followed by a menu: Info / Update / Reset / Units / Quit.

| Field | Value |
|---|---|
| Local name | `Body Smart XX`, where XX is a 2-hex-digit suffix (probably from the MAC) |
| Advertised service | `00000020-5749-5448-0010-000000000000`, i.e. WPP service `0x20`, model ID `0x0010`; the tail is all zeros, so no MAC is embedded |
| Manufacturer data | company `0x03FF`, payload `00000000` |
| Connectable | yes |
| TX power | 0 dBm |
| RSSI | −49 dBm at about 1 m |
| Advertising window | started about 18 s after the press and lasted about 15 s |

Why the first scans missed it: the scale doesn't advertise when idle or after a weigh-in (in Wi-Fi mode, on this firmware). It only advertised briefly once the button menu was open. The earlier scans probably caught nothing because nothing woke the advertising.

### GATT inventory (read-only, no pairing)

`tools/gatt_dump.py` connected during the advertising window. The connection needed no pairing prompt, and the negotiated MTU was 185.

| Service | Characteristic | Properties |
|---|---|---|
| `00000020-5749-5448-0010-000000000000` | `00000024-5749-5448-0010-000000000000` | notify, write, write-without-response |

That is the only service. CoreBluetooth hides the standard GAP/GATT services, and no Device Information or Battery service is exposed. This matches the WPP layout reported for Withings scales: a single characteristic carries every request (write) and response (notify).

### First PROBE (`tools/probe.py`)

The scale accepted a PROBE without link encryption or pairing. It replied in setup mode with `PROBE_REPLY` and `FACTORY_STATE`, which reports firmware 1311 and bootloader 2. The details are in [protocol.md](protocol.md). The raw capture stays in `captures/`, because the reply contains the MAC and the manufacturing ID.

### Bluetooth mode: advertisement after a weigh-in

The scale was switched to Bluetooth mode with the official app (see [user-guide.md](user-guide.md)). In a timed scan the user stepped on the scale when prompted.

| Field | Setup mode (button) | Bluetooth mode, after a weigh-in |
|---|---|---|
| Name | `Body Smart XX` | `Body Smart XX` |
| Service UUID tail | `000000000000` | **the scale's MAC** (12 hex digits) |
| Manufacturer data, company `0x03FF` | `00000000` | 4 non-zero bytes (meaning unknown; probably status or identity) |
| 0xFD77 service data | none | none (this model uses the "WITH" UUID form) |
| When | about 18 s after the press | about 60 s after stepping on, i.e. after the measurement finished |
| Seen | about 15 s | only twice, so the window is short |

### Bluetooth mode: probes

| Session | PROBE answer | Other requests |
|---|---|---|
| Button press | `PROBE_REPLY` + `FACTORY_STATE` (00), **no authentication**. `CONNECT_REASON` = 1 (button). | DISCONNECT is acknowledged. |
| Weigh-in | **`PROBE_CHALLENGE`** (35 bytes: MAC string + 16-byte challenge) | CONNECT_REASON, STORED_MEASURE (action 0) and DISCONNECT all return `CMD_ERROR` −5, "not authenticated". |

Conclusion: reading measurements needs the challenge answered with `kl`. That matches the app analysis in [protocol.md](protocol.md).

### First authenticated read (`tools/read_measurements.py`)

`kl` came from the user's own account via `tools/fetch_kl.py`: one association, model 16, 32-character `kl`. The session went:

1. PROBE → `PROBE_CHALLENGE`.
2. Our answer plus our own challenge → `PROBE_REPLY` plus the scale's answer. **Mutual authentication succeeded.**
3. CONNECT_REASON → 2 (weigh-in).
4. STORED_MEASURE action 0 → 4 groups stored.
5. Action 1 → those 4 groups as a multi-message list ending in Null.
6. DISCONNECT.

What the records showed:
- Each weigh-in produced **two groups with the same timestamp**: one with body composition, one with heart rate.
- Body-composition group: weight (1), fat mass (8), fat-free mass (5), hydration (77), bone mass (88), muscle mass (76), visceral fat (170), BMR (226), metabolic age (227), plus unnamed types 177, 178, 189, 201, 202, 203 and 207.
- Heart-rate group: heart rate (11).
- `STORED_MEASURE_META` carried three user IDs on this account. The parser accepted the layout without a separate array prefix.
- Extra TLVs 299 (meta extend) and 2451 (data position) also appeared; we don't parse them yet.

No delete was sent, so the readings should still sync to the official app.

Tooling note: macOS kills Bluetooth processes launched by the `claude` CLI (TCC: no usage description). Run Bluetooth tools with `tools/terminal_run.sh`.

### Coexistence with the phone app (observed)

- After the switch to Bluetooth mode, the first weigh-in was advertised only briefly. The user's phone (Bluetooth on) connected and synced it, and that reading then **did not appear** in our later read of the scale's storage. This matches the app analysis: the app deletes stored readings (action 2) after uploading them.
- Readings taken with the phone's Bluetooth off stayed stored on the scale, because we only read and never delete. Refreshing the phone app doesn't fetch them. A Bluetooth-mode scale only syncs when it advertises after a weigh-in, so the phone collects them at the next weigh-in.

Consequence for the HA integration: whoever connects first after a weigh-in gets the readings. If the phone syncs first, it deletes them before HA sees them. Options to evaluate:
- HA connects first (adapter or proxy close to the scale) and reads without deleting.
- Accept that HA only sees readings when the phone isn't around.
- Make HA the only reader, with optional delete and optional cloud upload.
