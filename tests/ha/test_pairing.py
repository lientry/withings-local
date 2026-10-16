"""Pairing through a BlueZ agent, against a fake system D-Bus."""

import asyncio
from unittest.mock import patch

from dbus_fast import Message, MessageType, Variant
from dbus_fast.errors import DBusError
import pytest

from custom_components.withings_local import pairing

PATH = "/org/bluez/hci0/dev_00_11_22_33_44_55"


class FakeBus:
    """Answers the BlueZ calls PairingSession makes; Pair() asks the exported agent for a code."""

    def __init__(self, correct=123456, already_paired=False, ask=True):
        self.correct, self.paired, self.ask = correct, already_paired, ask
        self.agents, self.calls = {}, []

    async def connect(self):
        return self

    def export(self, path, iface):
        self.agents[path] = iface

    def unexport(self, path):
        self.agents.pop(path, None)

    def disconnect(self):
        self.disconnected = True

    @staticmethod
    def _ok(body=(), signature=""):
        return Message(message_type=MessageType.METHOD_RETURN, reply_serial=1, body=list(body), signature=signature)

    @staticmethod
    def _err(name, text):
        return Message(message_type=MessageType.ERROR, reply_serial=1, error_name=name, body=[text], signature="s")

    async def call(self, msg):
        self.calls.append(msg.member)
        if msg.member == "Get":
            return self._ok([Variant("b", self.paired)], "v")
        if msg.member == "Pair":
            if not self.ask:
                self.paired = True
                return self._ok()
            agent = next(iter(self.agents.values()))
            try:
                code = await agent.request_passkey()
            except DBusError:
                return self._err("org.bluez.Error.AuthenticationCanceled", "Authentication Canceled")
            if code != self.correct:
                return self._err("org.bluez.Error.AuthenticationFailed", "Authentication Failed")
            self.paired = True
            return self._ok()
        return self._ok()


@pytest.fixture
def bus():
    fake = FakeBus()
    with patch.object(pairing, "MessageBus", lambda **kw: fake):
        yield fake


async def test_pairing_with_correct_code(bus):
    s = pairing.PairingSession(PATH)
    assert await s.start() is False
    assert "RegisterAgent" in bus.calls
    await s.wait_for_passkey_request()
    await s.submit_passkey(123456)
    assert bus.paired and "Disconnect" in bus.calls  # the link is released after pairing
    await s.close()
    assert "UnregisterAgent" in bus.calls and not bus.agents


async def test_wrong_code_fails(bus):
    s = pairing.PairingSession(PATH)
    await s.start()
    await s.wait_for_passkey_request()
    with pytest.raises(pairing.PairingFailed, match="AuthenticationFailed"):
        await s.submit_passkey(111111)
    await s.close()


async def test_already_paired_needs_no_code():
    fake = FakeBus(already_paired=True)
    with patch.object(pairing, "MessageBus", lambda **kw: fake):
        s = pairing.PairingSession(PATH)
        assert await s.start() is True
        assert "RegisterAgent" not in fake.calls
        await s.close()


async def test_no_code_requested_in_time(bus, monkeypatch):
    monkeypatch.setattr(pairing, "PASSKEY_REQUEST_TIMEOUT", 0.05)

    async def slow_pair(msg, _orig=bus.call):
        if msg.member == "Pair":
            await asyncio.sleep(1)
        return await _orig(msg)

    bus.call = slow_pair
    s = pairing.PairingSession(PATH)
    await s.start()
    with pytest.raises(pairing.PairingFailed, match="didn't ask for a code"):
        await s.wait_for_passkey_request()
    await s.close()
    assert "CancelPairing" in bus.calls  # the pending Pair() is cancelled


async def test_agent_gives_up_without_code(monkeypatch):
    monkeypatch.setattr(pairing, "PASSKEY_ENTRY_TIMEOUT", 0.05)
    agent = pairing.PasskeyAgent()
    with pytest.raises(DBusError):
        await agent.request_passkey()
    assert agent.passkey_requested.is_set()


def test_device_path_needs_local_linux_adapter(hass):
    from .conftest import service_info

    with patch.object(pairing.platform, "system", return_value="Darwin"):
        with pytest.raises(pairing.PairingUnsupported) as err:
            pairing.device_path(hass, service_info())
    assert err.value.reason == "pairing_not_available"
