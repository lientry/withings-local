# withings-local

Read measurements from a Withings smart scale over Bluetooth LE, locally, without the Withings cloud. Then use them in Home Assistant.

> **Status: early research.** Nothing here talks to a scale yet. See [PLAN.md](PLAN.md) for the roadmap.

**Target hardware:** Withings Body Smart (WBS13). Other Withings scales that use the same BLE protocol may follow.

## What this is
- A clean-room description of the scale's BLE protocol, in [`docs/`](docs/), written from interoperability research.
- A Python library and CLI to pull measurements from your own scale (planned).
- A Home Assistant custom integration that exposes those measurements as local sensors (planned).

## What this is not
- It contains no Withings code, firmware or app files, and none should ever be committed here.
- It is not a medical device. Values come from the scale as-is, with no guarantee of accuracy, and a firmware update may break things.

## Development
```bash
uv sync
uv run tools/ble_scan.py 60   # run from your own terminal, then step on the scale
```
On macOS, Bluetooth scripts need Bluetooth permission for the terminal app that runs them.

## Legal
This project exists to make hardware you own work with other software (interoperability). Withings is a trademark of Withings SA. This project is not affiliated with, endorsed by, or supported by Withings. Use it at your own risk.

## License
[MIT](LICENSE)
