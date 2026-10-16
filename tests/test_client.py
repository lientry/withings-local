"""WppSession against a fake Bluetooth client: timeouts must turn hangs into errors."""

import asyncio
from types import SimpleNamespace

import pytest

from withings_wpp import client as wpp_client

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
        await session.send(wpp_client.probe())


async def test_missing_reply_times_out():
    session = wpp_client.WppSession(FakeClient())
    await session.start()
    with pytest.raises(TimeoutError):
        await session.request(wpp_client.probe(), timeout=0.05)


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
        await session.request(wpp_client.probe(), timeout=1)
