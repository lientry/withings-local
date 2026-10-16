"""Decode stored measurement records (STORED_MEASURE action 1 replies)."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime

from .codec import Message, Reader, WppError
from .messages import Obj

# Measure type codes (shared with the public Withings API).
MEASURE_TYPES = {
    1: ("weight", "kg"),
    5: ("fat_free_mass", "kg"),
    6: ("fat_ratio", "%"),
    8: ("fat_mass", "kg"),
    11: ("heart_rate", "bpm"),
    76: ("muscle_mass", "kg"),
    77: ("hydration", "kg"),
    88: ("bone_mass", "kg"),
    170: ("visceral_fat", ""),  # index, per the public API
    226: ("basal_metabolic_rate", "kcal"),
    227: ("metabolic_age", "years"),
}
# Also observed from a Body Smart, meaning unknown: 177, 178, 189, 201, 202, 203, 207.


@dataclass(frozen=True)
class Measure:
    type: int
    value: float

    @property
    def name(self) -> str:
        return MEASURE_TYPES.get(self.type, (f"type_{self.type}", ""))[0]

    @property
    def unit(self) -> str:
        return MEASURE_TYPES.get(self.type, ("", ""))[1]


@dataclass
class MeasureGroup:
    """One weigh-in: a timestamp, the attributed user(s) and its values."""

    time: datetime
    user_ids: list[int]
    attrib: int
    uid: int
    measures: list[Measure] = field(default_factory=list)
    unknown_tlvs: list[int] = field(default_factory=list)

    def value(self, name: str) -> float | None:
        return next((m.value for m in self.measures if m.name == name), None)


def parse_meta(value: bytes) -> MeasureGroup:
    """STORED_MEASURE_META: uid u32, user count u8, user ids, attrib u8, time u32.

    The user-id list may or may not carry its own u8 count prefix after the count field. Accept
    whichever layout consumes the value exactly.
    """
    for prefixed in (False, True):
        try:
            r = Reader(value)
            uid = r.u32()
            count = r.u8()
            if prefixed:
                count = r.u8()
            users = [r.u32() for _ in range(count)]
            attrib = r.u8()
            time = r.u32()
            if r.remaining == 0:
                return MeasureGroup(datetime.fromtimestamp(time, UTC), users, attrib, uid)
        except WppError:
            continue
    raise WppError(f"unrecognised STORED_MEASURE_META layout ({len(value)} bytes)")


def parse_data(value: bytes) -> Measure:
    r = Reader(value)
    raw, mtype, exponent = r.i32(), r.u16(), r.i16()
    return Measure(mtype, round(raw * 10.0**exponent, max(0, -exponent)))


def parse_groups(messages: list[Message]) -> list[MeasureGroup]:
    groups: list[MeasureGroup] = []
    for msg in messages:
        for tlv in msg.tlvs:
            if tlv.type == Obj.STORED_MEASURE_META:
                groups.append(parse_meta(tlv.value))
            elif tlv.type == Obj.STORED_MEASURE_DATA:
                if not groups:
                    raise WppError("measure data before any meta record")
                groups[-1].measures.append(parse_data(tlv.value))
            elif tlv.type != Obj.NULL and groups:
                groups[-1].unknown_tlvs.append(tlv.type)
    return groups
