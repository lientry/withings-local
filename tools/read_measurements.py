"""Read stored measurements from the scale after a weigh-in (read-only).

Usage: uv run tools/read_measurements.py

Needs secrets/scale.json from tools/fetch_kl.py. Step on the scale; when it advertises (about a
minute later) the script connects, authenticates with kl, asks for the stored measurements and
disconnects. It never deletes measurements and never changes settings, so the Withings app can
still sync the same readings afterwards.

Measurements are personal health data. They are printed here and the raw exchange is saved to
captures/ble/ (git-ignored). Never commit either.
"""

import asyncio
import json
import time
from datetime import datetime
from pathlib import Path

from bleak import BleakClient, BleakScanner

from withings_wpp.advertisement import is_withings
from withings_wpp.client import ScaleClient, WppCommandError, WppSession
from withings_wpp.messages import ConnectReason

ROOT = Path(__file__).resolve().parent.parent
REASONS = {v: k for k, v in vars(ConnectReason).items() if not k.startswith("_")}


async def main() -> None:
    kl = json.loads((ROOT / "secrets" / "scale.json").read_text())["kl"]
    print(">>> Waiting up to 3 min. Step on the scale now and wait for the full reading. <<<\n", flush=True)
    found = asyncio.get_running_loop().create_future()

    def on_adv(device, adv):
        if is_withings(adv.service_uuids, adv.service_data) and not found.done():
            found.set_result(device)

    async with BleakScanner(on_adv):
        device = await asyncio.wait_for(found, 180)

    start = time.monotonic()
    trace = []

    def record(direction, raw):
        trace.append({"t": round(time.monotonic() - start, 3), "dir": direction, "hex": raw.hex()})

    try:
        async with BleakClient(device, timeout=20) as ble:
            session = WppSession(ble, trace=record)
            await session.start()
            scale = ScaleClient(session)
            result = await scale.authenticate(kl)
            if not result.authenticated:
                print("Scale didn't ask for authentication (button/setup session). Weigh in instead.")
                return
            print(f"✓ Authenticated (scale proved it knows kl too: {result.scale_verified})", flush=True)
            try:
                reason = await scale.connect_reason()
                print(f"  connect reason: {reason} ({REASONS.get(reason, '?')})", flush=True)
            except WppCommandError as e:
                print(f"  connect reason refused: {e}")
            status = await scale.measure_status()
            print(f"  stored measurement groups: {status.count}", flush=True)
            groups = await scale.measures() if status.count > 0 else []
            for g in groups:
                when = g.time.astimezone().strftime("%Y-%m-%d %H:%M:%S")
                values = ", ".join(f"{m.name}={m.value}{m.unit and ' ' + m.unit}" for m in g.measures)
                extra = f" (+ unparsed TLVs {sorted(set(g.unknown_tlvs))})" if g.unknown_tlvs else ""
                print(f"  {when}  users={len(g.user_ids)}  {values}{extra}")
            await scale.disconnect()
            await asyncio.sleep(0.5)
    finally:
        out = ROOT / "captures" / "ble" / f"session-{datetime.now():%Y%m%d-%H%M%S}.json"
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(trace, indent=2))
        print(f"\nRaw exchange saved to {out.relative_to(ROOT)} (contains health data: do not commit)")


if __name__ == "__main__":
    asyncio.run(main())
