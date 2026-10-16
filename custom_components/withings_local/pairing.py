"""One-time passkey pairing with the scale, through BlueZ.

The scale only lets a client subscribe to its notifications over an encrypted link bonded with
the 6-digit passkey it shows on its display. Home Assistant's BlueZ has no pairing agent, so on
its own it only attempts "Just Works" pairing, which the scale rejects.

We do what `bluetoothctl` does: register a temporary BlueZ pairing agent with the KeyboardOnly
capability on the system D-Bus, call `Device1.Pair()`, and answer the agent's `RequestPasskey`
with the code the user reads from the scale. BlueZ stores the bond, and every later connection
is encrypted automatically.

Only local adapters on Linux (BlueZ) can do this. ESPHome Bluetooth proxies and macOS are
reported as unsupported; macOS pairs by itself when the scale asks.
"""

import asyncio
import logging
import platform
import secrets

from dbus_fast import BusType, Message, MessageType
from dbus_fast.aio import MessageBus
from dbus_fast.errors import DBusError
from dbus_fast.service import ServiceInterface, method

from homeassistant.components import bluetooth
from homeassistant.components.bluetooth import BluetoothServiceInfoBleak
from homeassistant.core import HomeAssistant

_LOGGER = logging.getLogger(__name__)

BLUEZ = "org.bluez"
AGENT_CAPABILITY = "KeyboardOnly"
# BlueZ cancels an unanswered agent request after ~25 s and the kernel's pairing timeout is 30 s.
PASSKEY_REQUEST_TIMEOUT = 30.0
PASSKEY_ENTRY_TIMEOUT = 25.0
PAIRING_RESULT_TIMEOUT = 30.0


class PairingUnsupported(Exception):
    """Pairing can't be driven here (`reason` is a translation key)."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


class PairingFailed(Exception):
    """The scale or BlueZ rejected the pairing."""


class PasskeyAgent(ServiceInterface):
    """org.bluez.Agent1 that asks Home Assistant's user for the passkey."""

    def __init__(self) -> None:
        super().__init__("org.bluez.Agent1")
        self.passkey_requested = asyncio.Event()
        self._passkey: asyncio.Future[int] = asyncio.get_running_loop().create_future()
        self.cancelled = False

    def provide_passkey(self, passkey: int) -> None:
        if not self._passkey.done():
            self._passkey.set_result(passkey)

    async def request_passkey(self) -> int:
        """Signal that the scale wants its code and wait for the user to enter it."""
        self.passkey_requested.set()
        try:
            return await asyncio.wait_for(asyncio.shield(self._passkey), PASSKEY_ENTRY_TIMEOUT)
        except TimeoutError as err:
            raise DBusError("org.bluez.Error.Canceled", "no passkey entered in time") from err

    @method()
    async def RequestPasskey(self, device: "o") -> "u":  # noqa: N802, F821 - D-Bus API
        return await self.request_passkey()

    @method()
    def Cancel(self):  # noqa: N802 - D-Bus API
        self.cancelled = True
        self.passkey_requested.set()

    @method()
    def Release(self):  # noqa: N802 - D-Bus API
        return

    # dbus-fast reads these string annotations as D-Bus signatures, so this module must not use
    # `from __future__ import annotations`. Void methods carry no return annotation.
    # The scale asks for passkey entry; refuse everything else rather than guess.
    @method()
    def RequestPinCode(self, device: "o") -> "s":  # noqa: N802, F821
        raise DBusError("org.bluez.Error.Rejected", "PIN codes are not supported")

    @method()
    def RequestConfirmation(self, device: "o", passkey: "u"):  # noqa: N802, F821
        raise DBusError("org.bluez.Error.Rejected", "numeric comparison is not supported")

    @method()
    def RequestAuthorization(self, device: "o"):  # noqa: N802, F821
        raise DBusError("org.bluez.Error.Rejected", "authorization is not supported")

    @method()
    def AuthorizeService(self, device: "o", uuid: "s"):  # noqa: N802, F821
        raise DBusError("org.bluez.Error.Rejected", "service authorization is not supported")

    @method()
    def DisplayPasskey(self, device: "o", passkey: "u", entered: "q"):  # noqa: N802, F821
        return

    @method()
    def DisplayPinCode(self, device: "o", pincode: "s"):  # noqa: N802, F821
        return


def _check(reply: Message, what: str) -> Message:
    if reply.message_type == MessageType.ERROR:
        detail = reply.body[0] if reply.body else ""
        raise PairingFailed(f"{what}: {reply.error_name} {detail}".strip())
    return reply


class PairingSession:
    """One attempt: register the agent, Pair(), wait for the passkey request, answer it."""

    def __init__(self, device_path: str) -> None:
        self.device_path = device_path
        self.agent_path = f"/org/home_assistant/withings_local/agent_{secrets.token_hex(4)}"
        self._bus: MessageBus | None = None
        self._agent: PasskeyAgent | None = None
        self._pair_task: asyncio.Task[Message] | None = None

    async def _call(self, path: str, interface: str, member: str, signature: str = "", body=None) -> Message:
        assert self._bus is not None
        return await self._bus.call(
            Message(destination=BLUEZ, path=path, interface=interface, member=member, signature=signature, body=body or [])
        )

    async def is_paired(self) -> bool:
        reply = await self._call(
            self.device_path, "org.freedesktop.DBus.Properties", "Get", "ss", ["org.bluez.Device1", "Paired"]
        )
        return reply.message_type != MessageType.ERROR and bool(reply.body[0].value)

    async def start(self) -> bool:
        """Start pairing. Return True if the scale was already paired (nothing to enter)."""
        self._bus = await MessageBus(bus_type=BusType.SYSTEM, negotiate_unix_fd=False).connect()
        if await self.is_paired():
            return True
        self._agent = PasskeyAgent()
        self._bus.export(self.agent_path, self._agent)
        _check(
            await self._call("/org/bluez", "org.bluez.AgentManager1", "RegisterAgent", "os", [self.agent_path, AGENT_CAPABILITY]),
            "registering the pairing agent",
        )
        # Pair() connects if needed and returns once pairing has finished.
        self._pair_task = asyncio.ensure_future(self._call(self.device_path, "org.bluez.Device1", "Pair"))
        return False

    async def wait_for_passkey_request(self) -> None:
        """Return once the scale shows its code and BlueZ asks for it."""
        assert self._agent is not None and self._pair_task is not None
        waiter = asyncio.ensure_future(self._agent.passkey_requested.wait())
        try:
            done, _ = await asyncio.wait(
                {waiter, self._pair_task}, timeout=PASSKEY_REQUEST_TIMEOUT, return_when=asyncio.FIRST_COMPLETED
            )
        finally:
            if not waiter.done():
                waiter.cancel()
        if self._agent.cancelled:
            raise PairingFailed("the scale cancelled the pairing")
        if self._pair_task in done:
            _check(self._pair_task.result(), "pairing")
            raise PairingFailed("the scale paired without asking for a code")
        if not self._agent.passkey_requested.is_set():
            raise PairingFailed("the scale didn't ask for a code in time (is it in setup mode?)")

    async def submit_passkey(self, passkey: int) -> None:
        assert self._agent is not None and self._pair_task is not None
        self._agent.provide_passkey(passkey)
        try:
            reply = await asyncio.wait_for(asyncio.shield(self._pair_task), PAIRING_RESULT_TIMEOUT)
        except TimeoutError as err:
            raise PairingFailed("no pairing result from the scale") from err
        _check(reply, "pairing")
        if not await self.is_paired():
            raise PairingFailed("BlueZ didn't store the pairing")
        # Release the link: the scale won't accept a weigh-in session while it's held.
        await self._call(self.device_path, "org.bluez.Device1", "Disconnect")

    async def close(self) -> None:
        if self._pair_task is not None and not self._pair_task.done():
            self._pair_task.cancel()
            if self._bus is not None:
                await self._call(self.device_path, "org.bluez.Device1", "CancelPairing")
        if self._bus is not None:
            if self._agent is not None:
                await self._call("/org/bluez", "org.bluez.AgentManager1", "UnregisterAgent", "o", [self.agent_path])
                self._bus.unexport(self.agent_path)
            self._bus.disconnect()
        self._bus = self._agent = self._pair_task = None


def device_path(hass: HomeAssistant, service_info: BluetoothServiceInfoBleak) -> str:
    """BlueZ object path for the scale on the adapter that sees it, or raise PairingUnsupported."""
    if platform.system() != "Linux":
        raise PairingUnsupported("pairing_not_available")
    scanner = bluetooth.async_scanner_by_source(hass, service_info.source)
    if scanner is None or scanner.adapter_idx is None:
        raise PairingUnsupported("pairing_remote_adapter")
    details = getattr(service_info.device, "details", None) or {}
    if isinstance(details, dict) and isinstance(details.get("path"), str):
        return details["path"]
    return f"/org/bluez/{scanner.adapter}/dev_{service_info.address.upper().replace(':', '_')}"
