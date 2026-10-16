"""WPP command and object IDs, with builders and parsers for the messages we use."""

from __future__ import annotations

import struct
from dataclasses import dataclass

from .codec import Message, Reader, Tlv


class Cmd:
    ERROR = 256
    PROBE = 257
    STORED_MEASURE = 271
    SETUP_OK = 275
    SYNC_OK = 277
    PROBE_CHALLENGE = 296
    TIME_SET = 1281


class Obj:
    NULL = 256
    PROBE_REPLY = 257
    CONNECT_REASON = 280
    PROBE_CHALLENGE = 290
    PROBE_CHALLENGE_RESPONSE = 291
    APP_PROBE = 298
    FACTORY_STATE = 300
    APP_PROBE_OS_VERSION = 2344


COMMAND_NAMES = {v: k for k, v in vars(Cmd).items() if not k.startswith("_")}
OBJECT_NAMES = {v: k for k, v in vars(Obj).items() if not k.startswith("_")}

# AppProbe identifies the client: os 1 = Android, app 1 = the Withings phone app.
OS_ANDROID = 1
APP_WITHINGS = 1


def probe(app_version: int, os_version: int) -> Message:
    return Message(
        Cmd.PROBE,
        (
            Tlv(Obj.APP_PROBE, struct.pack(">BBI", OS_ANDROID, APP_WITHINGS, app_version)),
            Tlv(Obj.APP_PROBE_OS_VERSION, struct.pack(">H", os_version)),
        ),
    )


@dataclass(frozen=True)
class ProbeReply:
    vid: int
    pid: int
    name: str
    mac: str
    secret: str
    hard_version: int
    mfg_id: str
    bl_version: int
    soft_version: int
    rescue_version: int
    extra: bytes

    @classmethod
    def parse(cls, value: bytes) -> ProbeReply:
        r = Reader(value)
        return cls(
            vid=r.u16(),
            pid=r.u16(),
            name=r.str_(),
            mac=r.str_(),
            secret=r.str_(),
            hard_version=r.u32(),
            mfg_id=r.str_(),
            bl_version=r.u32(),
            soft_version=r.u32(),
            rescue_version=r.u32(),
            extra=r.rest(),
        )


@dataclass(frozen=True)
class ProbeChallenge:
    mac: str
    challenge: bytes
    extra: bytes

    @classmethod
    def parse(cls, value: bytes) -> ProbeChallenge:
        r = Reader(value)
        return cls(mac=r.str_(), challenge=r.bytes_(), extra=r.rest())


def describe(msg: Message) -> str:
    """One-line summary that never includes TLV values (they can hold identifiers)."""
    cmd = COMMAND_NAMES.get(msg.base_command, f"0x{msg.base_command:04x}")
    origin = "device-request " if msg.from_device else ""
    objs = ", ".join(f"{OBJECT_NAMES.get(t.type, f'0x{t.type:04x}')}[{len(t.value)}]" for t in msg.tlvs)
    return f"{origin}{cmd}({msg.base_command}): {objs or '-'}"
