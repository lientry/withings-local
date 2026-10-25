"""Connect to the device after a measurement and read its stored measurements."""

from __future__ import annotations

from dataclasses import dataclass, field
from collections.abc import Callable
import asyncio
from datetime import datetime
import logging
import time

from bleak_retry_connector import BleakClientWithServiceCache, establish_connection
from .withings_wpp.advertisement import FD77, Fd77, WithingsUuid
from .withings_wpp.client import WppSession, read_measurements
from .withings_wpp.devices import BEAMO, BODY_SMART, PROFILES, DeviceProfile
from .withings_wpp.measures import MeasureGroup, merge_by_time

from homeassistant.components import bluetooth
from homeassistant.components.bluetooth import BluetoothChange, BluetoothScanningMode, BluetoothServiceInfoBleak
from homeassistant.components.bluetooth.active_update_coordinator import (
    ActiveBluetoothDataUpdateCoordinator,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_ADDRESS
from homeassistant.core import CALLBACK_TYPE, HomeAssistant, callback
from homeassistant.util import dt as dt_util

from .const import (
    CONF_KL,
    CONF_MODEL,
    IDLE_POLL_SECONDS,
    OPT_KNOWN_USERS,
    POLL_COOLDOWN_SECONDS,
    SESSION_TIMEOUT_SECONDS,
)

_LOGGER = logging.getLogger(__name__)

type WithingsLocalConfigEntry = ConfigEntry[WithingsScaleCoordinator]


# The value a device's sensors are built around, when it measures other things too.
REQUIRED_VALUE = {BEAMO.model_id: "body_temperature"}


def entry_profile(entry: ConfigEntry) -> DeviceProfile:
    """The device an entry is for. Entries from before BeamO support have no model: Body Smart."""
    return PROFILES.get(entry.data.get(CONF_MODEL, BODY_SMART.model_id), BODY_SMART)


@dataclass
class WeighIn:
    """One person's latest weigh-in."""

    measured_at: datetime
    values: dict[str, float]


@dataclass
class ScaleData:
    """What the last sync read: each user's latest weigh-in plus scale-level state."""

    users: dict[int, WeighIn] = field(default_factory=dict)
    firmware: int | None = None
    battery: int | None = None
    last_sync: datetime | None = None


def latest_per_user(groups: list[MeasureGroup], require: str | None = None) -> dict[int, WeighIn]:
    """Each user's newest weigh-in (merged across same-timestamp groups), plus a derived fat ratio.

    User 0 collects weigh-ins the scale couldn't attribute to anyone. With `require`, only
    measurements that include that value count, so a newer one of another kind (say, a BeamO ECG)
    doesn't hide it.
    """
    latest: dict[int, WeighIn] = {}
    for g in merge_by_time(groups):  # oldest first, so later ones win
        values = {m.name: m.value for m in g.measures}
        if require is not None and require not in values:
            continue
        if (weight := values.get("weight")) and (fat := values.get("fat_mass")) is not None:
            values.setdefault("fat_ratio", round(fat / weight * 100, 2))
        latest[g.user_id] = WeighIn(g.time, values)
    return latest


WITHINGS_COMPANY_ID = 0x03FF


def fd77(service_info: BluetoothServiceInfoBleak, profile: DeviceProfile) -> Fd77 | None:
    """The FD77 service data, if it's this model's."""
    data = next((v for k, v in service_info.service_data.items() if k.lower() == FD77), None)
    fd = Fd77.parse(bytes(data)) if data else None
    return fd if fd and fd.model_id == profile.model_id else None


def has_new_data(service_info: BluetoothServiceInfoBleak, profile: DeviceProfile = BODY_SMART) -> bool:
    """True when the device advertises as installed, which it does after a measurement.

    Body Smart: two signals, because passive scanners may not receive the scan response:
    - the service UUID tail carries the scale's MAC (all zeros in setup/button sessions);
    - the Withings manufacturer data is non-zero (all zeros in setup sessions).

    BeamO: the "installed" flag in the FD77 data (off in setup mode).
    """
    if profile is not BODY_SMART:
        return bool((fd := fd77(service_info, profile)) and fd.installed)
    for uuid in service_info.service_uuids:
        w = WithingsUuid.parse(uuid)
        if w and w.model_id == BODY_SMART.model_id and w.tail.strip("0"):
            return True
    mfr = service_info.manufacturer_data.get(WITHINGS_COMPANY_ID)
    return bool(mfr) and any(mfr)


def sync_requested(service_info: BluetoothServiceInfoBleak, profile: DeviceProfile) -> bool:
    """The device says it has data for us. Body Smart: any installed advertisement."""
    if profile is BODY_SMART:
        return has_new_data(service_info, profile)
    return bool((fd := fd77(service_info, profile)) and fd.wants_connection)


def _is_bonded(device) -> bool:
    """BlueZ reports Paired on the device object; unknown elsewhere (assume bonded)."""
    details = getattr(device, "details", None)
    if not isinstance(details, dict) or "props" not in details:
        return True
    return bool(details["props"].get("Paired"))


def is_setup_mode(service_info: BluetoothServiceInfoBleak) -> bool:
    """True when the scale advertises in setup mode (button held 3 s): its service UUID then has
    an all-zero tail. Home Assistant merges a device's advertisement data with earlier packets,
    so weigh-in data (MAC tail, manufacturer bytes) may still be present; only look for the
    setup-mode UUID."""
    return any(
        (w := WithingsUuid.parse(u)) and w.model_id == BODY_SMART.model_id and not w.tail.strip("0")
        for u in service_info.service_uuids
    )


def ready_to_pair(service_info: BluetoothServiceInfoBleak, profile: DeviceProfile) -> bool:
    """The advertisement to start pairing on.

    Body Smart: setup mode, the only time it shows a code. BeamO: any advertisement. It's
    reported to ask for the code whenever an unpaired client connects, and its setup mode (the QR
    code) is how the Withings app adds it to an account, which we don't want to trigger.
    """
    if profile is BODY_SMART:
        return is_setup_mode(service_info)
    return fd77(service_info, profile) is not None


class WithingsScaleCoordinator(ActiveBluetoothDataUpdateCoordinator[ScaleData]):
    """Poll the scale whenever it advertises new measurements."""

    def __init__(self, hass: HomeAssistant, entry: WithingsLocalConfigEntry) -> None:
        self._kl: str = entry.data[CONF_KL]
        self.profile = entry_profile(entry)
        self._entry = entry
        self.config_entry_id = entry.entry_id
        self.title = entry.title
        # Users seen so far, in order of first appearance; persisted so their entities exist after a restart.
        self.known_users: list[int] = list(entry.options.get(OPT_KNOWN_USERS, []))
        self._new_user_listeners: list[Callable[[list[int]], None]] = []
        self._pairing_requested = False
        # BeamO: HA's debouncer runs a poll requested during another one 10 s later without asking
        # again, which would skip the cooldowns; so while one is scheduled or running, don't ask
        # for another. A scheduled poll that never starts (HA stopping, say) stops counting after
        # a while; a running one counts until it ends, however long its retries take.
        self._poll_scheduled_since: float | None = None
        self._polling = False
        super().__init__(
            hass=hass,
            logger=_LOGGER,
            address=entry.data[CONF_ADDRESS],
            mode=BluetoothScanningMode.ACTIVE,
            needs_poll_method=self._needs_poll,
            poll_method=self._async_sync,
            connectable=True,
        )
        self.data = ScaleData()

    @callback
    def async_start(self) -> CALLBACK_TYPE:
        stop = super().async_start()
        if self.profile is BODY_SMART:
            return stop
        # HA only reports advertisements that changed. A BeamO that keeps advertising the same data
        # must still be looked at once IDLE_POLL_SECONDS have passed, so listen to every one.
        cancel = bluetooth.async_register_advertisement_callback(self.hass, self._async_on_advertisement, self.address)

        @callback
        def _stop() -> None:
            cancel()
            stop()

        return _stop

    @callback
    def _async_on_advertisement(self, service_info: BluetoothServiceInfoBleak) -> None:
        if service_info.connectable:
            self._async_handle_bluetooth_event(service_info, BluetoothChange.ADVERTISEMENT)

    @callback
    def _async_request_pairing(self) -> None:
        """Ask the user to pair (reauth flow). HA keeps a single flow per entry."""
        if not self._pairing_requested:
            self._pairing_requested = True
            self._entry.async_start_reauth(self.hass)

    @callback
    def async_add_new_user_listener(self, listener: Callable[[list[int]], None]) -> CALLBACK_TYPE:
        """Call `listener` with the IDs of users seen for the first time."""
        self._new_user_listeners.append(listener)
        return lambda: self._new_user_listeners.remove(listener)

    @callback
    def _register_users(self, user_ids) -> None:
        new = [u for u in user_ids if u not in self.known_users]
        if not new:
            return
        self.known_users.extend(new)
        self.hass.config_entries.async_update_entry(
            self._entry, options={**self._entry.options, OPT_KNOWN_USERS: self.known_users}
        )
        for listener in list(self._new_user_listeners):
            listener(new)

    @callback
    def _needs_poll(self, service_info: BluetoothServiceInfoBleak, seconds_since_last_poll: float | None) -> bool:
        new_data = has_new_data(service_info, self.profile)
        requested = sync_requested(service_info, self.profile)
        # The cooldown only avoids re-reading after a successful sync; after a failure, retry while
        # the device is still advertising (its window is short). An installed BeamO that doesn't
        # ask for a sync is only looked at every IDLE_POLL_SECONDS, or POLL_COOLDOWN_SECONDS after
        # a failure: it may advertise for much longer than a scale, and must not be hammered.
        if requested:
            cooldown, retry_now = POLL_COOLDOWN_SECONDS, not self.last_poll_successful
        else:
            cooldown = IDLE_POLL_SECONDS if self.last_poll_successful else POLL_COOLDOWN_SECONDS
            retry_now = False
        due = seconds_since_last_poll is None or seconds_since_last_poll >= cooldown or retry_now
        fd = fd77(service_info, self.profile)
        _LOGGER.debug(
            "%s: advertisement via %s (rssi %s, connectable %s, uuids %d, withings mfr data %s, fd77 %s): "
            "new data %s, sync requested %s, poll due %s",
            self.title,
            service_info.source,
            service_info.rssi,
            service_info.connectable,
            len(service_info.service_uuids),
            "present" if WITHINGS_COMPANY_ID in service_info.manufacturer_data else "absent",
            # Flags only; the other fields can hold the MAC.
            "absent" if fd is None else f"installed {fd.installed}, sync requested {fd.sync_requested}, fields {sorted(fd.fields)}",
            new_data,
            requested,
            due,
        )
        if not (new_data and due):
            return False
        if self.profile is not BODY_SMART:
            now = time.monotonic()
            scheduled = self._poll_scheduled_since
            if self._polling or (scheduled is not None and now - scheduled < 2 * SESSION_TIMEOUT_SECONDS):
                return False
            self._poll_scheduled_since = now
        return True

    async def _async_sync(self, service_info: BluetoothServiceInfoBleak) -> ScaleData:
        self._polling, self._poll_scheduled_since = True, None
        try:
            return await self._async_read(service_info)
        finally:
            self._polling = False

    async def _async_read(self, service_info: BluetoothServiceInfoBleak) -> ScaleData:
        _LOGGER.info(
            "%s: measurement advertised, connecting via %s (rssi %s)", self.title, service_info.source, service_info.rssi
        )
        device = bluetooth.async_ble_device_from_address(self.hass, service_info.address, connectable=True)
        started = time.monotonic()
        step = "connecting"
        session: WppSession | None = None

        def on_disconnect(_client) -> None:
            _LOGGER.debug("%s: device disconnected after %.1fs", self.title, time.monotonic() - started)
            if session is not None:
                session.mark_disconnected()

        def fresh_device():
            # Retries use the newest BLEDevice (the best adapter may change between attempts).
            return bluetooth.async_ble_device_from_address(self.hass, self.address, connectable=True) or (
                device or service_info.device
            )

        try:
            client = await establish_connection(
                BleakClientWithServiceCache,
                device or service_info.device,
                self.title,
                disconnected_callback=on_disconnect,
                max_attempts=3,
                ble_device_callback=fresh_device,
            )
            step = "reading"
            _LOGGER.debug("%s: connected after %.1fs", self.title, time.monotonic() - started)
            try:
                # A stuck session must never block later syncs.
                session = WppSession(client, profile=self.profile)
                async with asyncio.timeout(SESSION_TIMEOUT_SECONDS):
                    result = await read_measurements(client, self._kl, session)
            finally:
                await client.disconnect()
        except Exception as err:
            # HA's coordinator only logs the first failure in a row; log every one so users can debug range issues.
            needs_pairing = step == "reading" and "subscrib" in str(err) and not _is_bonded(device or service_info.device)
            if needs_pairing:
                hint = " The device needs to be paired with Home Assistant; a repair notification will guide you."
                self._async_request_pairing()
            elif step == "connecting":
                hint = " " + bluetooth.async_address_reachability_diagnostics(
                    self.hass, self.address, bluetooth.BluetoothReachabilityIntent.CONNECTION
                )
            else:
                hint = ""
            _LOGGER.warning(
                "%s: sync failed while %s after %.1fs via %s (rssi %s): %s: %s%s",
                self.title,
                step,
                time.monotonic() - started,
                service_info.source,
                service_info.rssi,
                type(err).__name__,
                err,
                hint,
            )
            raise

        if not result.authenticated:
            _LOGGER.debug("%s: session without authentication (button press?), nothing to read", self.title)
            return self.data
        if not result.scale_verified:
            # A device that fails our challenge doesn't know kl: don't record what it sends
            # (anyone in range can copy the advertisement). A real scale always passes.
            _LOGGER.warning("%s: the device did not prove it knows the key; ignoring its readings", self.title)
            return self.data

        users = dict(self.data.users)
        for user_id, weigh_in in latest_per_user(result.groups, REQUIRED_VALUE.get(self.profile.model_id)).items():
            if user_id not in users or weigh_in.measured_at >= users[user_id].measured_at:
                users[user_id] = weigh_in
        data = ScaleData(
            users=users,
            firmware=result.firmware or self.data.firmware,
            battery=result.battery if result.battery is not None else self.data.battery,
            last_sync=dt_util.utcnow(),
        )
        self._register_users(sorted(users, key=lambda u: users[u].measured_at))
        for g in merge_by_time(result.groups):
            _LOGGER.debug("%s: stored measurement %s, user %s, %d values", self.title, g.time, g.user_id, len(g.measures))
        _LOGGER.info(
            "%s: sync done: %d measurement(s) stored on the device, %d user(s)", self.title, len(result.groups), len(users)
        )
        return data
