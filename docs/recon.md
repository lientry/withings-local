# Recon log

Observations from our own scale (Body Smart, WBS13, in Wi-Fi mode). Raw scans stay in git-ignored `captures/`. This file only records conclusions, with no addresses or neighbouring devices.

## 2026-10-16 — BLE advertisement scans (macOS, CoreBluetooth via bleak)

| Scan | Trigger | Result |
|---|---|---|
| 90 s | none (scale idle) | no Withings advertisement |
| 90 s | user stepped on the scale | no Withings advertisement; no new strong (> −75 dBm) advertiser |
| 120 s | short press of the button under the scale | no Withings advertisement; two new, empty advertisements at about −78 dBm (no name, UUIDs or manufacturer data), not identified |

Each scan matched on "WITH" service UUIDs (`-5749-5448-`) and on names containing withings/wbs/body/scale.

Open questions:
- Distance and walls between the Mac and the scale (range).
- Does this firmware advertise after a weigh-in while in Wi-Fi mode? Prior work reports about 55 s of advertising on the Body Smart.
- What does the button press do on this model (Bluetooth icon on the display? setup mode?).

Tooling note: macOS kills Bluetooth processes launched by the `claude` CLI (TCC: no usage description). Run Bluetooth tools with `tools/terminal_run.sh`.
