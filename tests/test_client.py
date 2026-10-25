"""WppSession against a fake Bluetooth client: timeouts must turn hangs into errors."""

import asyncio
import dataclasses
import struct
from types import SimpleNamespace

import pytest

from withings_wpp import auth
from withings_wpp import client as wpp_client
from withings_wpp.codec import Message, Tlv, pack_str
from withings_wpp.devices import BEAMO, BODY_SMART
from withings_wpp.messages import Cmd, MeasureAction, Obj, probe

CHAR = SimpleNamespace(uuid="00000024-5749-5448-0010-000000000000")


class FakeClient:
    def __init__(self, hang_subscribe=False, hang_write=False):
        self.services = [SimpleNamespace(characteristics=[CHAR])]
        self.hang_subscribe, self.hang_write = hang_subscribe, hang_write

    async def start_notify(self, char, callback):
        if self.hang_subscribe:
            await asyncio.Event().wait()

    async def write_gatt_char(self, char, data, response=True):
        if self.hang_write:
            await asyncio.Event().wait()


# Synthetic test values only.
MAC = "00:11:22:33:44:55"
KL = "test-kl-not-a-real-secret-000000"
DEVICE_CHALLENGE = bytes(range(16))


class FakeScale(FakeClient):
    """Answers like a scale that asks for authentication, after pushing `on_subscribe` messages
    unprompted (as the BeamO is reported to do)."""

    def __init__(self, on_subscribe=(), knows_kl=True):
        super().__init__()
        self.on_subscribe, self.knows_kl = on_subscribe, knows_kl
        self.sent: list[Message] = []
        self._notify = None

    def push(self, msg):
        self._notify(CHAR, bytearray(msg.encode()))

    async def start_notify(self, char, callback):
        self._notify = callback
        for msg in self.on_subscribe:
            self.push(msg)

    async def write_gatt_char(self, char, data, response=True):
        from withings_wpp.codec import decode_message

        msg = decode_message(bytes(data))
        self.sent.append(msg)
        for reply in self.answer(msg):
            asyncio.get_running_loop().call_soon(self.push, reply)

    def answer(self, msg):
        if msg.command == Cmd.PROBE:
            return [Message(Cmd.PROBE_CHALLENGE, (Tlv(Obj.PROBE_CHALLENGE, pack_str(MAC) + pack_str(DEVICE_CHALLENGE)),))]
        if msg.command == Cmd.PROBE_CHALLENGE:
            theirs = msg.find(Obj.PROBE_CHALLENGE)[0].value[len(MAC) + 2 :]
            key = KL if self.knows_kl else "wrong-key"
            return [Message(Cmd.PROBE, (Tlv(Obj.PROBE_CHALLENGE_RESPONSE, pack_str(auth.answer(theirs, MAC, key))),))]
        if msg.command == Cmd.BATTERY_PERCENT:
            return [Message(Cmd.BATTERY_PERCENT, (Tlv(Obj.BATTERY_PERCENT, struct.pack(">H", 80)),))]
        if msg.command == Cmd.CONNECT_REASON:
            return [Message(Cmd.CONNECT_REASON, (Tlv(Obj.CONNECT_REASON, struct.pack(">H", 2)),))]
        if msg.command == Cmd.STORED_MEASURE:
            status = struct.pack(">hib", 0, 0, 1)
            return [Message(Cmd.STORED_MEASURE, (Tlv(Obj.STORED_MEASURE_STATUS, status),))]
        if msg.command == Cmd.SYNC_OK:
            return [Message(Cmd.SYNC_OK)]
        return []


# What a BeamO is reported to push right after the subscription, before any request.
STARTUP = (
    Message(Cmd.PROBE, (Tlv(Obj.FACTORY_STATE, b"\x00"),)),
    Message(Cmd.CONNECT_REASON, (Tlv(Obj.CONNECT_REASON, struct.pack(">H", 1)),)),
    Message(Cmd.BATTERY_PERCENT, (Tlv(Obj.BATTERY_PERCENT, struct.pack(">H", 5)),)),
)


async def test_hanging_subscribe_times_out(monkeypatch):
    monkeypatch.setattr(wpp_client, "SUBSCRIBE_TIMEOUT", 0.05)
    session = wpp_client.WppSession(FakeClient(hang_subscribe=True))
    with pytest.raises(TimeoutError, match="subscribing to notifications"):
        await session.start()


async def test_hanging_write_times_out(monkeypatch):
    monkeypatch.setattr(wpp_client, "WRITE_TIMEOUT", 0.05)
    session = wpp_client.WppSession(FakeClient(hang_write=True))
    await session.start()
    with pytest.raises(TimeoutError):
        await session.send(probe())


async def test_missing_reply_times_out():
    session = wpp_client.WppSession(FakeClient())
    await session.start()
    with pytest.raises(TimeoutError):
        await session.request(probe(), timeout=0.05)


async def test_disconnect_fails_pending_subscribe_immediately():
    session = wpp_client.WppSession(FakeClient(hang_subscribe=True))
    asyncio.get_running_loop().call_later(0.01, session.mark_disconnected)
    with pytest.raises(wpp_client.ScaleDisconnected, match="subscribing"):
        async with asyncio.timeout(1):  # must not wait for the 15 s subscribe timeout
            await session.start()


async def test_disconnect_fails_pending_reply_immediately():
    session = wpp_client.WppSession(FakeClient())
    await session.start()
    asyncio.get_running_loop().call_later(0.01, session.mark_disconnected)
    with pytest.raises(wpp_client.ScaleDisconnected, match="reply"):
        await session.request(probe(), timeout=1)


async def test_unsolicited_startup_messages_dont_answer_requests():
    ble = FakeScale(on_subscribe=STARTUP)
    result = await wpp_client.read_measurements(ble, KL)
    assert result.authenticated and result.scale_verified
    assert result.connect_reason == 2 and result.battery == 80


async def test_unsolicited_message_while_waiting_is_ignored():
    ble = FakeScale()
    session = wpp_client.WppSession(ble)
    await session.start()
    ble.answer = lambda msg: [STARTUP[2], Message(Cmd.CONNECT_REASON, (Tlv(Obj.CONNECT_REASON, struct.pack(">H", 2)),))]
    assert await wpp_client.ScaleClient(session).connect_reason() == 2


async def test_error_for_the_request_is_raised():
    ble = FakeScale()
    session = wpp_client.WppSession(ble)
    await session.start()
    ble.answer = lambda msg: [Message(Cmd.ERROR, (Tlv(Obj.CMD_ERROR, struct.pack(">Hi", Cmd.BATTERY_PERCENT, -3)),))]
    with pytest.raises(wpp_client.WppCommandError, match="unsupported"):
        await wpp_client.ScaleClient(session).battery()


async def test_unverified_device_gets_no_further_commands():
    ble = FakeScale(knows_kl=False)
    result = await wpp_client.read_measurements(ble, KL)
    assert result.authenticated and not result.scale_verified and result.groups == []
    assert [m.command for m in ble.sent] == [Cmd.PROBE, Cmd.PROBE_CHALLENGE, Cmd.DISCONNECT]


async def test_sync_ok_policy_covers_both_directions():
    ble = FakeScale()
    session = wpp_client.WppSession(ble, profile=dataclasses.replace(BODY_SMART, sync_ok=False))
    await wpp_client.read_measurements(ble, KL, session)
    ble.push(Message(Cmd.SYNC_OK | wpp_client.DEVICE_REQUEST))
    await asyncio.sleep(0.01)  # the answer goes out from a background task
    sent = [m.base_command for m in ble.sent]
    assert Cmd.SYNC_OK not in sent and Cmd.ERROR in sent  # the device's request is refused, not echoed
    assert stored_actions(ble) == [MeasureAction.GET_STATE]


async def test_sync_ok_is_sent_by_default():
    ble = FakeScale()
    await wpp_client.read_measurements(ble, KL)
    assert Cmd.SYNC_OK in [m.command for m in ble.sent]


def stored_actions(ble):
    return [m.find(Obj.STORED_MEASURE_ACTION)[0].value[0] for m in ble.sent if m.command == Cmd.STORED_MEASURE]


# Reported: startup messages, sometimes with an early challenge of their own.
BEAMO_STARTUP = (*STARTUP, Message(Cmd.PROBE_CHALLENGE, (Tlv(Obj.PROBE_CHALLENGE, pack_str(MAC) + pack_str(bytes(16))),)))
BEAMO_CHAR = SimpleNamespace(uuid="00000004-0000-5749-5448-494e47530000")


class FakeBeamO(FakeScale):
    """Two Withings characteristics; only 0004 speaks WPP. Pushes its startup messages a little
    after the subscription, and only answers the PROBE that asks for a challenge."""

    def __init__(self, startup=BEAMO_STARTUP, startup_delay=0.02, **kwargs):
        super().__init__(**kwargs)
        self.startup = startup
        other = SimpleNamespace(uuid="00000005-0000-5749-5448-494e47530000")
        self.services = [SimpleNamespace(characteristics=[other, BEAMO_CHAR])]
        self.startup_delay = startup_delay

    def push(self, msg):
        self._notify(BEAMO_CHAR, bytearray(msg.encode()))

    async def start_notify(self, char, callback):
        assert char is BEAMO_CHAR
        self._notify = callback
        for msg in self.startup:
            asyncio.get_running_loop().call_later(self.startup_delay, self.push, msg)

    def answer(self, msg):
        if msg.command == Cmd.PROBE and not msg.find(Obj.CHALLENGE_REQUEST):
            return []
        return super().answer(msg)


async def test_beamo_session_waits_out_startup_messages():
    ble = FakeBeamO()
    session = wpp_client.WppSession(ble, profile=dataclasses.replace(BEAMO, settle_seconds=0.05))
    result = await wpp_client.read_measurements(ble, KL, session)
    assert result.authenticated and result.scale_verified
    assert ble.sent[0].encode() == BEAMO.probe().encode()
    assert Cmd.SYNC_OK not in [m.base_command for m in ble.sent]
    assert stored_actions(ble) == [MeasureAction.GET_STATE]  # never DELETE_ALL


async def test_beamo_startup_probe_isnt_taken_as_the_answer():
    # A late startup PROBE arrives while we wait for the challenge: it's ignored, not taken as
    # "no authentication needed".
    ble = FakeBeamO(startup=())
    session = wpp_client.WppSession(ble, profile=dataclasses.replace(BEAMO, settle_seconds=0))
    await session.start()
    answer = ble.answer
    ble.answer = lambda msg: ([STARTUP[0]] if msg.command == Cmd.PROBE else []) + answer(msg)
    result = await wpp_client.ScaleClient(session).authenticate(KL)
    assert result.authenticated and result.scale_verified
