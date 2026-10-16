"""Passive BLE scan: print every advertisement, flagging likely Withings devices.

Usage: uv run tools/ble_scan.py [seconds]
Step on the scale (or press its button) while this runs so it wakes up and advertises.
"""

import asyncio
import json
import sys
from datetime import datetime
from pathlib import Path

from bleak import BleakScanner

HINTS = ("withings", "wbs", "body", "scale", "nokia")
# Withings WPP UUIDs look like 000000XX-5749-5448-MMMM-<id>: "5749-5448" is ASCII "WITH",
# MMMM is the model id, and the last group may carry the device's identity MAC.
WITH_MARKER = "-5749-5448-"
OUT = Path(__file__).resolve().parent.parent / "captures" / "ble"


def withings_uuids(uuids) -> list[dict]:
    out = []
    for u in uuids:
        u = u.lower()
        if WITH_MARKER in u:
            parts = u.split("-")
            out.append({"uuid": u, "short": parts[0][-2:], "model_id": f"0x{parts[3]}", "tail": parts[4]})
    return out


def is_candidate(name: str | None, uuids=()) -> bool:
    return bool(withings_uuids(uuids)) or (bool(name) and any(h in name.lower() for h in HINTS))


async def main(seconds: float) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    seen: dict[str, dict] = {}

    def on_adv(device, adv):
        rec = {
            "address": device.address,
            "name": adv.local_name or device.name,
            "rssi": adv.rssi,
            "service_uuids": sorted(adv.service_uuids),
            "manufacturer_data": {f"0x{k:04x}": v.hex() for k, v in adv.manufacturer_data.items()},
            "service_data": {k: v.hex() for k, v in adv.service_data.items()},
            "tx_power": adv.tx_power,
            "withings": withings_uuids(adv.service_uuids),
        }
        if device.address not in seen or (rec["withings"] and not seen[device.address]["withings"]):
            flag = "  <-- candidate" if is_candidate(rec["name"], adv.service_uuids) else ""
            print(f"{rec['address']}  {rec['rssi']:>4} dBm  {rec['name']!r}{flag}")
        seen[device.address] = rec

    print(f">>> Scanning for {seconds:.0f}s. Step on the scale now. <<<\n", flush=True)
    async with BleakScanner(on_adv):
        await asyncio.sleep(seconds)

    path = OUT / f"scan-{datetime.now():%Y%m%d-%H%M%S}.json"
    path.write_text(json.dumps(list(seen.values()), indent=2))
    candidates = [r for r in seen.values() if is_candidate(r["name"], r["service_uuids"])]
    print(f"\n{len(seen)} devices, {len(candidates)} candidate(s). Saved {path}")
    for r in candidates:
        print(json.dumps(r, indent=2))


if __name__ == "__main__":
    asyncio.run(main(float(sys.argv[1]) if len(sys.argv) > 1 else 20))
