"""WPP message framing and TLV encoding.

Wire format (all integers big-endian):

    message = version:u8 (0x01) | command:u16 | length:u16 | payload[length]
    payload = TLV*
    TLV     = type:u16 | length:u16 | value[length]

Bit 0x4000 in the command marks a request initiated by the device. Strings and byte arrays inside
TLV values carry a 1-byte length prefix. Notifications arrive fragmented to the ATT MTU and are
reassembled using the header length.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass, field

PROTOCOL_VERSION = 0x01
HEADER = struct.Struct(">BHH")
TLV_HEADER = struct.Struct(">HH")
DEVICE_REQUEST = 0x4000


class WppError(ValueError):
    """Malformed WPP data."""


@dataclass(frozen=True)
class Tlv:
    type: int
    value: bytes

    def encode(self) -> bytes:
        return TLV_HEADER.pack(self.type, len(self.value)) + self.value


@dataclass(frozen=True)
class Message:
    command: int
    tlvs: tuple[Tlv, ...] = ()

    @property
    def base_command(self) -> int:
        return self.command & ~DEVICE_REQUEST

    @property
    def from_device(self) -> bool:
        return bool(self.command & DEVICE_REQUEST)

    def find(self, tlv_type: int) -> list[Tlv]:
        return [t for t in self.tlvs if t.type == tlv_type]

    def encode(self) -> bytes:
        payload = b"".join(t.encode() for t in self.tlvs)
        return HEADER.pack(PROTOCOL_VERSION, self.command, len(payload)) + payload


def decode_tlvs(payload: bytes) -> tuple[Tlv, ...]:
    tlvs, pos = [], 0
    while pos < len(payload):
        if pos + TLV_HEADER.size > len(payload):
            raise WppError(f"truncated TLV header at offset {pos}")
        tlv_type, length = TLV_HEADER.unpack_from(payload, pos)
        pos += TLV_HEADER.size
        if pos + length > len(payload):
            raise WppError(f"TLV 0x{tlv_type:04x} claims {length} bytes, {len(payload) - pos} left")
        tlvs.append(Tlv(tlv_type, payload[pos : pos + length]))
        pos += length
    return tuple(tlvs)


def decode_message(data: bytes) -> Message:
    if len(data) < HEADER.size:
        raise WppError("shorter than a header")
    version, command, length = HEADER.unpack_from(data)
    if version != PROTOCOL_VERSION:
        raise WppError(f"unexpected protocol version 0x{version:02x}")
    if len(data) != HEADER.size + length:
        raise WppError(f"length field says {length}, got {len(data) - HEADER.size}")
    return Message(command, decode_tlvs(data[HEADER.size :]))


@dataclass
class Reassembler:
    """Join notification fragments into whole messages."""

    _buf: bytearray = field(default_factory=bytearray)

    def feed(self, fragment: bytes) -> list[Message]:
        self._buf += fragment
        out = []
        while len(self._buf) >= HEADER.size:
            if self._buf[0] != PROTOCOL_VERSION:
                raise WppError(f"stream out of sync (first byte 0x{self._buf[0]:02x})")
            _, _, length = HEADER.unpack_from(self._buf)
            total = HEADER.size + length
            if len(self._buf) < total:
                break
            out.append(decode_message(bytes(self._buf[:total])))
            del self._buf[:total]
        return out

    @property
    def pending(self) -> int:
        return len(self._buf)


class Reader:
    """Sequential reader for fields inside a TLV value."""

    def __init__(self, data: bytes) -> None:
        self._data, self._pos = data, 0

    def _take(self, n: int) -> bytes:
        if self._pos + n > len(self._data):
            raise WppError(f"need {n} bytes at offset {self._pos}, have {len(self._data) - self._pos}")
        chunk = self._data[self._pos : self._pos + n]
        self._pos += n
        return chunk

    def u8(self) -> int:
        return self._take(1)[0]

    def i8(self) -> int:
        return int.from_bytes(self._take(1), "big", signed=True)

    def u16(self) -> int:
        return int.from_bytes(self._take(2), "big")

    def i16(self) -> int:
        return int.from_bytes(self._take(2), "big", signed=True)

    def u32(self) -> int:
        return int.from_bytes(self._take(4), "big")

    def i32(self) -> int:
        return int.from_bytes(self._take(4), "big", signed=True)

    def bytes_(self) -> bytes:
        return self._take(self.u8())

    def str_(self) -> str:
        return self.bytes_().decode("utf-8", "replace")

    def rest(self) -> bytes:
        return self._take(len(self._data) - self._pos)

    @property
    def remaining(self) -> int:
        return len(self._data) - self._pos


def pack_str(value: str | bytes) -> bytes:
    raw = value.encode() if isinstance(value, str) else value
    if len(raw) > 255:
        raise WppError("string longer than 255 bytes")
    return bytes([len(raw)]) + raw
