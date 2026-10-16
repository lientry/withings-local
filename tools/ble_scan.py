"""Passive BLE scan: record every advertisement, flagging likely Withings devices.

Usage: uv run tools/ble_scan.py [seconds] [--press-at SECONDS]

With --press-at, the script tells you when to wake the scale (step on it / press its button),
then lists devices first seen after that moment, which are the likely candidates.
"""

import argparse
import asyncio
import json
import time
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


def raw_fields(adv) -> dict:
    """Platform advertisement dict (CoreBluetooth on macOS), stringified, to catch fields bleak doesn't map."""
    for item in adv.platform_data or ():
        if hasattr(item, "items"):
            return {str(k): str(v) for k, v in item.items()}
    return {}


async def main(seconds: float, press_at: float | None) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    seen: dict[str, dict] = {}
    start = time.monotonic()

    def on_adv(device, adv):
        t = round(time.monotonic() - start, 1)
        rec = seen.get(device.address)
        if rec is None:
            rec = seen[device.address] = {"address": device.address, "first_seen": t, "count": 0, "max_rssi": adv.rssi}
            new = True
        else:
            new = False
        rec.update(
            name=adv.local_name or device.name or rec.get("name"),
            last_seen=t,
            rssi=adv.rssi,
            max_rssi=max(rec["max_rssi"], adv.rssi),
            service_uuids=sorted(set(rec.get("service_uuids", [])) | set(adv.service_uuids)),
            manufacturer_data={**rec.get("manufacturer_data", {}), **{f"0x{k:04x}": v.hex() for k, v in adv.manufacturer_data.items()}},
            service_data={**rec.get("service_data", {}), **{k: v.hex() for k, v in adv.service_data.items()}},
            tx_power=adv.tx_power,
            raw={**rec.get("raw", {}), **raw_fields(adv)},
        )
        rec["count"] += 1
        rec["withings"] = withings_uuids(rec["service_uuids"])
        if new:
            flag = "  <-- candidate" if is_candidate(rec["name"], rec["service_uuids"]) else ""
            print(f"[{t:6.1f}s] {rec['rssi']:>4} dBm  {rec['name']!r}{flag}", flush=True)

    async with BleakScanner(on_adv):
        if press_at is None:
            print(f">>> Scanning for {seconds:.0f}s. Step on the scale now. <<<\n", flush=True)
            await asyncio.sleep(seconds)
        else:
            print(f">>> Scanning {seconds:.0f}s. Learning the background for {press_at:.0f}s; DON'T touch the scale yet. <<<\n", flush=True)
            await asyncio.sleep(press_at)
            print("\n" + "=" * 60 + "\n>>> NOW: press the scale's button (short press) / step on it <<<\n" + "=" * 60 + "\n", flush=True)
            await asyncio.sleep(seconds - press_at)

    path = OUT / f"scan-{datetime.now():%Y%m%d-%H%M%S}.json"
    path.write_text(json.dumps({"press_at": press_at, "devices": list(seen.values())}, indent=2))
    candidates = [r for r in seen.values() if is_candidate(r["name"], r["service_uuids"])]
    print(f"\n{len(seen)} devices, {len(candidates)} candidate(s). Saved {path}")
    for r in candidates:
        print(json.dumps(r, indent=2))
    if press_at is not None:
        after = sorted((r for r in seen.values() if r["first_seen"] >= press_at), key=lambda r: -r["max_rssi"])
        print(f"\nFirst seen after the press ({len(after)}):")
        for r in after:
            print(f"  +{r['first_seen'] - press_at:5.1f}s..{r['last_seen'] - press_at:5.1f}s  max {r['max_rssi']} dBm  x{r['count']}  {r['name']!r}  raw keys={sorted(r['raw'])}")


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("seconds", nargs="?", type=float, default=20)
    p.add_argument("--press-at", type=float)
    a = p.parse_args()
    asyncio.run(main(a.seconds, a.press_at))
