"""WPP command and object IDs, with builders and parsers for the messages we use.

IDs are protocol facts from interoperability analysis (see docs/protocol.md). Commands and TLV
object types share one number space, but they are separate tables.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass

from .codec import Message, Reader, Tlv


class Cmd:
    ERROR = 256
    PROBE = 257
    BATTERY_PERCENT = 261
    SCALE_SESSION = 269  # setup/sync init only; don't send
    STORED_MEASURE = 271
    DISCONNECT = 272
    CONNECT_REASON = 273
    USER_UNIT = 274  # writes units on the scale; don't send
    SETUP_OK = 275  # finalises setup; don't send
    SYNC_OK = 277
    PROBE_CHALLENGE = 296
    ASSOCIATION_KEYS_SET = 308  # re-keys the scale; never send
    SYNC_REQUEST = 321
    TIME_SET = 1281
    TIME_GET = 1291


class Obj:
    NULL = 256
    PROBE_REPLY = 257
    BATTERY_PERCENT = 263
    CMD_ERROR = 272
    STORED_MEASURE_ACTION = 276
    STORED_MEASURE_STATUS = 277
    STORED_MEASURE_META = 278
    STORED_MEASURE_DATA = 279
    CONNECT_REASON = 280
    PROBE_CHALLENGE = 290
    PROBE_CHALLENGE_RESPONSE = 291
    APP_PROBE = 298
    STORED_MEASURE_META_EXTEND = 299
    FACTORY_STATE = 300
    TIME_SET = 1281
    TIME_SET_REPLY = 1282
    APP_PROBE_OS_VERSION = 2344


class MeasureAction:
    GET_STATE = 0
    GET_ALL = 1
    DELETE_ALL = 2  # sent by the phone app after uploading; destructive, opt-in only


class ConnectReason:
    UNKNOWN = 0
    USER_REQUEST = 1  # button
    DEVICE_REQUEST = 2  # weigh-in: the only reason the app runs a measurement sync for


COMMAND_NAMES = {v: k for k, v in vars(Cmd).items() if not k.startswith("_")}
OBJECT_NAMES = {v: k for k, v in vars(Obj).items() if not k.startswith("_")}
ERROR_CODES = {-2: "busy", -3: "unsupported", -4: "rejected", -5: "not authenticated", -8: "invalid arguments", -9: "arguments not set"}

# AppProbe identifies the client: os 1 = Android, app 1 = the Withings phone app.
OS_ANDROID = 1
APP_WITHINGS = 1
APP_VERSION = 202609240  # value current app versions send
ANDROID_API_LEVEL = 34


def probe(app_version: int = APP_VERSION, os_version: int = ANDROID_API_LEVEL) -> Message:
    return Message(
        Cmd.PROBE,
        (
            Tlv(Obj.APP_PROBE, struct.pack(">BBI", OS_ANDROID, APP_WITHINGS, app_version)),
            Tlv(Obj.APP_PROBE_OS_VERSION, struct.pack(">H", os_version)),
        ),
    )


def connect_reason_request() -> Message:
    return Message(Cmd.CONNECT_REASON)


def battery_request() -> Message:
    return Message(Cmd.BATTERY_PERCENT)


def stored_measure(action: int) -> Message:
    return Message(Cmd.STORED_MEASURE, (Tlv(Obj.STORED_MEASURE_ACTION, struct.pack(">Bb", action, 0)),))


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


@dataclass(frozen=True)
class CmdError:
    cmd: int
    err: int

    @classmethod
    def parse(cls, value: bytes) -> CmdError:
        r = Reader(value)
        return cls(cmd=r.u16(), err=r.i32())

    def __str__(self) -> str:
        return f"cmd {self.cmd}: {ERROR_CODES.get(self.err, self.err)}"


@dataclass(frozen=True)
class StoredMeasureStatus:
    count: int
    oldest_time: int
    wifi_configured: int

    @classmethod
    def parse(cls, value: bytes) -> StoredMeasureStatus:
        r = Reader(value)
        return cls(count=r.i16(), oldest_time=r.i32(), wifi_configured=r.i8())


def describe(msg: Message) -> str:
    """One-line summary that never includes TLV values (they can hold identifiers)."""
    cmd = COMMAND_NAMES.get(msg.base_command, f"0x{msg.base_command:04x}")
    origin = "device-request " if msg.from_device else ""
    objs = ", ".join(f"{OBJECT_NAMES.get(t.type, f'0x{t.type:04x}')}[{len(t.value)}]" for t in msg.tlvs)
    return f"{origin}{cmd}({msg.base_command}): {objs or '-'}"
