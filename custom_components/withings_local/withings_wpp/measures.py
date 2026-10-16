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
    """STORED_MEASURE_META: uid u32, valid u8, ids u8-length array of u32, attrib u8, time u32.

    Only the first `valid` IDs are meaningful; the rest of the array is junk. User IDs and `uid`
    are not reliable enough to use as keys; deduplicate on (time, measure type) instead.
    """
    r = Reader(value)
    uid = r.u32()
    valid = r.u8()
    ids = [r.u32() for _ in range(r.u8())]
    attrib = r.u8()
    time = r.u32()
    if r.remaining:
        raise WppError(f"STORED_MEASURE_META has {r.remaining} unexpected trailing bytes")
    return MeasureGroup(datetime.fromtimestamp(time, UTC), ids[:valid], attrib, uid)


def parse_data(value: bytes) -> Measure:
    r = Reader(value)
    raw, mtype, exponent = r.i32(), r.u16(), r.i16()
    return Measure(mtype, round(raw * 10.0**exponent, max(0, -exponent)))


def merge_by_time(groups: list[MeasureGroup]) -> list[MeasureGroup]:
    """One group per timestamp with one value per measure type, oldest first.

    The scale returns its whole store on every sync, and one weigh-in arrives as several groups
    (e.g. body composition and heart rate) sharing a timestamp.
    """
    merged: dict[datetime, MeasureGroup] = {}
    for g in groups:
        m = merged.setdefault(g.time, MeasureGroup(g.time, g.user_ids, g.attrib, g.uid))
        by_type = {x.type: x for x in m.measures} | {x.type: x for x in g.measures}
        m.measures = list(by_type.values())
        m.unknown_tlvs = sorted(set(m.unknown_tlvs) | set(g.unknown_tlvs))
    return [merged[t] for t in sorted(merged)]


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
