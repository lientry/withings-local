"""Send one WPP PROBE to a waking Withings scale and record everything it says back.

Usage: uv run tools/probe.py [--app-version N] [--os-version N] [--listen SECONDS]

Safe by design. The script sends only PROBE and never answers device requests such as SETUP_OK,
so a setup-mode session ends with "Setup failed" on the display and nothing on the scale changes.
If the link needs encryption, macOS shows a pairing dialog: type the code shown on the scale.

The console redacts identifiers (MAC, secret, manufacturing ID). Raw fragments are saved to
captures/ble/probe-<timestamp>.json, which is git-ignored: never commit it.
"""

import argparse
import asyncio
import json
import time
from datetime import datetime
from pathlib import Path

from bleak import BleakClient, BleakScanner

from withings_wpp.codec import Reassembler
from withings_wpp.messages import Obj, ProbeChallenge, ProbeReply, describe, probe

WITH_MARKER = "-5749-5448-"
CHAR_SHORT = "00000024"
OUT = Path(__file__).resolve().parent.parent / "captures" / "ble"


def redacted(s: str) -> str:
    return f"<{len(s)} chars>"


def summarize(msg) -> list[str]:
    lines = [describe(msg)]
    for tlv in msg.tlvs:
        try:
            if tlv.type == Obj.PROBE_REPLY:
                p = ProbeReply.parse(tlv.value)
                lines.append(
                    f"    ProbeReply: vid={p.vid} pid={p.pid} name={p.name!r} mac={redacted(p.mac)} "
                    f"secret={redacted(p.secret)} mfg_id={redacted(p.mfg_id)} hw={p.hard_version} "
                    f"bootloader={p.bl_version} firmware={p.soft_version} rescue={p.rescue_version} "
                    f"extra={len(p.extra)}B"
                )
            elif tlv.type == Obj.PROBE_CHALLENGE:
                c = ProbeChallenge.parse(tlv.value)
                lines.append(f"    ProbeChallenge: mac={redacted(c.mac)} challenge={len(c.challenge)}B extra={len(c.extra)}B")
        except Exception as e:  # noqa: BLE001 - layout guesses can be wrong; keep the raw capture
            lines.append(f"    could not parse 0x{tlv.type:04x}: {e}")
    return lines


async def main(args) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    print(">>> Waiting for the scale. Short-press its button now. <<<\n", flush=True)
    found = asyncio.get_running_loop().create_future()

    def on_adv(device, adv):
        if any(WITH_MARKER in u.lower() for u in adv.service_uuids) and not found.done():
            found.set_result(device)

    async with BleakScanner(on_adv):
        try:
            device = await asyncio.wait_for(found, 90)
        except TimeoutError:
            print("No Withings advertisement seen.")
            return

    log = {"sent": [], "received": [], "events": []}
    start = time.monotonic()
    stamp = lambda: round(time.monotonic() - start, 3)  # noqa: E731
    reasm = Reassembler()
    last_rx = [time.monotonic()]

    def on_notify(_char, data: bytearray):
        last_rx[0] = time.monotonic()
        log["received"].append({"t": stamp(), "hex": bytes(data).hex()})
        try:
            for msg in reasm.feed(bytes(data)):
                for line in summarize(msg):
                    print(f"[{stamp():6.2f}s] <- {line}" if not line.startswith(" ") else line, flush=True)
        except Exception as e:  # noqa: BLE001
            print(f"[{stamp():6.2f}s] !! decode error: {e}", flush=True)
            log["events"].append({"t": stamp(), "decode_error": repr(e)})

    try:
        async with BleakClient(device, timeout=20) as client:
            char = next(
                c for s in client.services for c in s.characteristics if c.uuid.startswith(CHAR_SHORT) and WITH_MARKER in c.uuid
            )
            print(f"[{stamp():6.2f}s] connected, MTU {client.mtu_size}", flush=True)
            await client.start_notify(char, on_notify)
            msg = probe(args.app_version, args.os_version)
            raw = msg.encode()
            log["sent"].append({"t": stamp(), "hex": raw.hex()})
            print(f"[{stamp():6.2f}s] -> {describe(msg)}", flush=True)
            await client.write_gatt_char(char, raw, response=True)
            print(f"[{stamp():6.2f}s] write acknowledged", flush=True)
            last_rx[0] = time.monotonic()
            while time.monotonic() - last_rx[0] < args.listen and client.is_connected:
                await asyncio.sleep(0.2)
            log["events"].append({"t": stamp(), "end": "connected" if client.is_connected else "device disconnected"})
    except Exception as e:  # noqa: BLE001 - record whatever happened
        print(f"[{stamp():6.2f}s] !! {type(e).__name__}: {e}", flush=True)
        log["events"].append({"t": stamp(), "error": repr(e)})

    if reasm.pending:
        print(f"{reasm.pending} bytes left unassembled")
    path = OUT / f"probe-{datetime.now():%Y%m%d-%H%M%S}.json"
    path.write_text(json.dumps(log, indent=2))
    print(f"\nSaved raw capture to {path} (do not commit)")


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--app-version", type=int, default=1, help="AppProbe version field (real value TBD from the app)")
    p.add_argument("--os-version", type=int, default=34, help="AppProbeOsVersion, e.g. Android API level")
    p.add_argument("--listen", type=float, default=8, help="seconds to keep listening after the last message")
    asyncio.run(main(p.parse_args()))
