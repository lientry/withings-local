"""Decode Withings BLE advertisements.

Two forms exist:
- A 128-bit service UUID `000000SS-5749-5448-MMMM-<12 hex>`, where "5749-5448" is ASCII "WITH",
  MMMM is the model ID and the last group may hold the device MAC (all zeros in setup mode).
- Service data on the 16-bit UUID 0xFD77. It starts with a u16 (version in the top nibble,
  model ID in the low 12 bits), followed by small TLVs whose header byte packs type and length
  in nibbles. Type 1 is a flags byte:
  - bit0: installed
  - bit1: sync requested (the scale has data and wants a connection)
  - bit2: wake-up

  Type 2 holds the MAC in setup mode. Headers put the type in the high nibble: a BeamO's
  reported advertisements `10 47 11 00 26 <MAC>` (setup) and `10 47 11 01 34 …` (installed)
  parse as model 71 with these fields.
"""

from __future__ import annotations

from dataclasses import dataclass, field

WITH_MARKER = "-5749-5448-"
FD77 = "0000fd77-0000-1000-8000-00805f9b34fb"


@dataclass(frozen=True)
class WithingsUuid:
    service: int
    model_id: int
    tail: str

    @classmethod
    def parse(cls, uuid: str) -> WithingsUuid | None:
        u = uuid.lower()
        if WITH_MARKER not in u:
            return None
        parts = u.split("-")
        if parts[1:3] != ["5749", "5448"]:
            # Withings' newer service (00000000-0000-5749-5448-…) carries no model: use FD77.
            return None
        return cls(service=int(parts[0], 16), model_id=int(parts[3], 16), tail=parts[4])


@dataclass(frozen=True)
class Fd77:
    version: int
    model_id: int
    installed: bool | None = None
    sync_requested: bool | None = None
    wake_up: bool | None = None
    fields: dict[int, bytes] = field(default_factory=dict)

    @property
    def wants_connection(self) -> bool:
        return bool(self.installed and self.sync_requested)

    @classmethod
    def parse(cls, data: bytes) -> Fd77 | None:
        if len(data) < 2:
            return None
        head = int.from_bytes(data[:2], "big")
        fields: dict[int, bytes] = {}
        pos = 2
        while pos < len(data):
            tlv_type, length = data[pos] >> 4, data[pos] & 0x0F
            fields[tlv_type] = data[pos + 1 : pos + 1 + length]
            pos += 1 + length
        flags = fields.get(1)
        f = flags[0] if flags else None
        return cls(
            version=head >> 12,
            model_id=head & 0x0FFF,
            installed=None if f is None else bool(f & 1),
            sync_requested=None if f is None else bool(f & 2),
            wake_up=None if f is None else bool(f & 4),
            fields=fields,
        )


def is_withings(service_uuids, service_data: dict) -> bool:
    return any(WITH_MARKER in u.lower() for u in service_uuids) or FD77 in {k.lower() for k in service_data}
