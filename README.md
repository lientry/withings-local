# withings-local

Read measurements from a Withings smart scale over Bluetooth LE, locally, without the Withings cloud, and use them in Home Assistant.

> **Status: working prototype.** It reads weigh-ins from a Body Smart (WBS13), and the values match the Withings app. The Home Assistant integration is new and not yet tested on a real installation.

## What's here

| Path | What |
|---|---|
| `custom_components/withings_local/` | Home Assistant integration: Bluetooth discovery, setup, sensors for the latest weigh-in |
| `src/withings_wpp/` | Python library (`withings-wpp`): clean-room client for the scale's Bluetooth protocol, read-only |
| `tools/` | CLI helpers: scan, probe, `fetch_kl.py` (get your scale's key), `read_measurements.py` |
| `docs/` | Protocol notes, recon log, [user guide](docs/user-guide.md) |

**Supported:** Withings Body Smart (WBS13) in **Bluetooth mode**. Wi-Fi mode is not supported (see the [user guide](docs/user-guide.md)). Other Withings scales using the same protocol may work but are untested.

**Sensors:**
- weight, fat mass, fat ratio, fat-free mass, muscle mass, bone mass, water mass
- visceral fat, basal metabolic rate, metabolic age, heart rate
- time of the last weigh-in

## How it works

1. After a weigh-in, the scale advertises over Bluetooth for a short time.
2. Home Assistant connects through a local adapter or an ESPHome Bluetooth proxy.
3. It proves it knows the scale's key (`kl`), then reads the stored measurements.
4. Nothing is deleted, so the Withings app still syncs the same readings when your phone is nearby.

You get `kl` once, from your own Withings account: the integration's setup can fetch it with your login, or you can paste it.

## Development
```bash
uv sync --group ha
uv run pytest
uv run tools/ble_scan.py 60   # run from your own terminal, then step on the scale
```
On macOS, Bluetooth scripts need Bluetooth permission for the terminal app that runs them.

## Prior art and thanks

This project builds on public work by others. We read these projects for understanding; no code was copied from them.

- [openwithings](https://github.com/totruok/openwithings) (MIT): protocol notes and tools for the Body+ (WBS05). Our starting point for the message framing, the probe and challenge exchange, and the account-key flow.
- [esphome-withings-wpp](https://github.com/NavistAuLabs/esphome-withings-wpp): an ESPHome component that reads a Body Smart on an ESP32. Use it if you prefer a dedicated ESPHome device.
- [Gadgetbridge](https://codeberg.org/Freeyourgadget/Gadgetbridge): its Withings Steel HR support documents the same protocol family for watches.
- [withouthings](https://github.com/DavidVentura/withouthings) and [scanwatch_ble](https://github.com/SureshotM6/scanwatch_ble): the same protocol on Withings ScanWatch watches.

## Not
- **No Withings code.** The repo contains no Withings code, firmware or app files, and must never contain any.
- **Not a medical device.** Values are as reported by the scale, with no guarantee of accuracy. Firmware updates may break things.

## Legal
This project exists for interoperability with hardware you own. Withings is a trademark of Withings SA. This project is not affiliated with, endorsed by or supported by Withings. Use it at your own risk.

## License
[MIT](LICENSE)
