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

Tooling note: macOS kills Bluetooth processes launched by the `claude` CLI (TCC: no usage description). Run Bluetooth tools with `tools/terminal_run.sh`.
