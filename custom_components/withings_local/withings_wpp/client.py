"""Talk WPP to a Withings scale over a connected bleak client.

Only read operations are exposed. Commands that change the scale (setup, association keys,
units, Wi-Fi, firmware, deleting measurements) are deliberately not implemented here.
"""

from __future__ import annotations

import asyncio
import logging
import struct
from dataclasses import dataclass

from bleak import BleakClient
from bleak.backends.characteristic import BleakGATTCharacteristic

from . import auth
from .codec import DEVICE_REQUEST, Message, Reassembler, Tlv
from .measures import MeasureGroup, merge_by_time, parse_groups
from .messages import (
    Cmd,
    CmdError,
    MeasureAction,
    Obj,
    ProbeChallenge,
    ProbeReply,
    StoredMeasureStatus,
    battery_request,
    connect_reason_request,
    describe,
    probe,
    stored_measure,
)

_LOGGER = logging.getLogger(__name__)
WITH_MARKER = "-5749-5448-"
CHAR_PREFIX = "00000024"
ERR_UNSUPPORTED = -3
SUBSCRIBE_TIMEOUT = 15.0
WRITE_TIMEOUT = 10.0


class WppCommandError(Exception):
    def __init__(self, error: CmdError) -> None:
        super().__init__(str(error))
        self.error = error


class AuthenticationError(Exception):
    pass


def find_wpp_characteristic(client: BleakClient) -> BleakGATTCharacteristic:
    for service in client.services:
        for char in service.characteristics:
            if char.uuid.startswith(CHAR_PREFIX) and WITH_MARKER in char.uuid:
                return char
    raise LookupError("Withings WPP characteristic not found")


@dataclass
class Authenticated:
    reply: ProbeReply | None
    authenticated: bool
    scale_verified: bool


class WppSession:
    """Request/response over the single WPP characteristic."""

    def __init__(self, client: BleakClient, trace=None) -> None:
        self._client = client
        self._char = find_wpp_characteristic(client)
        self._reasm = Reassembler()
        self._inbox: asyncio.Queue[Message] = asyncio.Queue()
        self._trace = trace or (lambda direction, raw: None)

    async def start(self) -> None:
        _LOGGER.debug("subscribing to notifications on %s", self._char.uuid)
        try:
            async with asyncio.timeout(SUBSCRIBE_TIMEOUT):
                await self._client.start_notify(self._char, self._on_notify)
        except TimeoutError as err:
            raise TimeoutError(
                f"subscribing to notifications took more than {SUBSCRIBE_TIMEOUT:.0f}s "
                "(the Bluetooth stack may be trying to pair with the scale)"
            ) from err
        _LOGGER.debug("subscribed")

    def _on_notify(self, _char, data: bytearray) -> None:
        self._trace("rx", bytes(data))
        for msg in self._reasm.feed(bytes(data)):
            _LOGGER.debug("<- %s", describe(msg))
            if msg.from_device and msg.base_command != Cmd.ERROR:
                asyncio.get_running_loop().create_task(self._answer_device_request(msg))
            else:
                self._inbox.put_nowait(msg)

    async def _answer_device_request(self, msg: Message) -> None:
        if msg.base_command == Cmd.SYNC_OK:
            # The scale expects its sync acknowledgement echoed back.
            await self.send(Message(Cmd.SYNC_OK | DEVICE_REQUEST))
            return
        # Like the phone app does for requests it doesn't handle: reply "unsupported".
        err = Tlv(Obj.CMD_ERROR, struct.pack(">Hi", msg.base_command, ERR_UNSUPPORTED))
        await self.send(Message(Cmd.ERROR | DEVICE_REQUEST, (err,)))

    async def send(self, msg: Message) -> None:
        raw = msg.encode()
        _LOGGER.debug("-> %s", describe(msg))
        self._trace("tx", raw)
        async with asyncio.timeout(WRITE_TIMEOUT):
            await self._client.write_gatt_char(self._char, raw, response=True)

    async def request(self, msg: Message, *, multi: bool = False, timeout: float = 5.0) -> list[Message]:
        """Send and collect the reply. Multi-message replies end with a Null TLV."""
        await self.send(msg)
        replies: list[Message] = []
        loop = asyncio.get_running_loop()
        deadline = loop.time() + timeout
        while True:
            remaining = deadline - loop.time()
            if remaining <= 0:
                if replies:
                    return replies
                raise TimeoutError(f"no reply to command {msg.command}")
            reply = await asyncio.wait_for(self._inbox.get(), remaining)
            if reply.base_command == Cmd.ERROR:
                (tlv,) = reply.find(Obj.CMD_ERROR) or (None,)
                if tlv is not None:
                    raise WppCommandError(CmdError.parse(tlv.value))
                raise WppCommandError(CmdError(msg.command, 0))
            replies.append(reply)
            if not multi or reply.find(Obj.NULL):
                return replies


class ScaleClient:
    """High-level read-only scale operations."""

    def __init__(self, session: WppSession) -> None:
        self.session = session

    async def authenticate(self, kl: str) -> Authenticated:
        (reply,) = await self.session.request(probe())
        if reply.base_command == Cmd.PROBE:
            # Setup/button session: the scale didn't ask for authentication.
            tlvs = reply.find(Obj.PROBE_REPLY)
            return Authenticated(ProbeReply.parse(tlvs[0].value) if tlvs else None, False, False)
        tlvs = reply.find(Obj.PROBE_CHALLENGE)
        if reply.base_command != Cmd.PROBE_CHALLENGE or not tlvs:
            raise AuthenticationError(f"unexpected probe answer: {describe(reply)}")
        challenge = ProbeChallenge.parse(tlvs[0].value)
        own = auth.new_challenge()
        (final,) = await self.session.request(auth.challenge_reply(challenge.challenge, challenge.mac, kl, own))
        probe_reply = final.find(Obj.PROBE_REPLY)
        their_answer = final.find(Obj.PROBE_CHALLENGE_RESPONSE)
        verified = bool(their_answer) and auth.verify(their_answer[0].value[1:], own, challenge.mac, kl)
        return Authenticated(ProbeReply.parse(probe_reply[0].value) if probe_reply else None, True, verified)

    async def connect_reason(self) -> int:
        (reply,) = await self.session.request(connect_reason_request())
        (tlv,) = reply.find(Obj.CONNECT_REASON)
        return int.from_bytes(tlv.value[:2], "big")

    async def battery(self) -> int:
        """Battery level in percent (a read; the phone app asks for it on every sync)."""
        (reply,) = await self.session.request(battery_request())
        (tlv,) = reply.find(Obj.BATTERY_PERCENT)
        return int.from_bytes(tlv.value[:2], "big")

    async def measure_status(self) -> StoredMeasureStatus:
        (reply,) = await self.session.request(stored_measure(MeasureAction.GET_STATE))
        (tlv,) = reply.find(Obj.STORED_MEASURE_STATUS)
        return StoredMeasureStatus.parse(tlv.value)

    async def measures(self) -> list[MeasureGroup]:
        replies = await self.session.request(stored_measure(MeasureAction.GET_ALL), multi=True, timeout=10)
        return parse_groups(replies)

    async def sync_ok(self) -> None:
        """Acknowledge the sync. Reported as required: without it the scale may ignore the next
        connection. Reported not to delete or mark readings, so the phone app still gets them."""
        await self.session.request(Message(Cmd.SYNC_OK), timeout=3)

    async def disconnect(self) -> None:
        # The phone app sends this without waiting for an answer.
        await self.session.send(Message(Cmd.DISCONNECT))


@dataclass
class SyncResult:
    authenticated: bool
    scale_verified: bool
    connect_reason: int | None
    firmware: int | None
    groups: list[MeasureGroup]
    battery: int | None = None


async def read_measurements(ble: BleakClient, kl: str) -> SyncResult:
    """Run one read-only session on a connected client: authenticate, read, disconnect."""
    session = WppSession(ble)
    await session.start()
    scale = ScaleClient(session)
    auth_result = await scale.authenticate(kl)
    firmware = auth_result.reply.soft_version if auth_result.reply else None
    if not auth_result.authenticated:
        return SyncResult(False, False, None, firmware, [])
    try:
        battery = await scale.battery()
    except (WppCommandError, TimeoutError, ValueError):
        _LOGGER.debug("battery level not available", exc_info=True)
        battery = None
    try:
        reason = await scale.connect_reason()
    except WppCommandError:
        reason = None
    status = await scale.measure_status()
    groups = merge_by_time(await scale.measures()) if status.count > 0 else []
    try:
        await scale.sync_ok()
    except (WppCommandError, TimeoutError):
        _LOGGER.debug("SYNC_OK not acknowledged", exc_info=True)
    try:
        await scale.disconnect()
    except Exception:  # noqa: BLE001 - the scale may already be gone
        _LOGGER.debug("disconnect message not delivered", exc_info=True)
    return SyncResult(True, auth_result.scale_verified, reason, firmware, groups, battery)
