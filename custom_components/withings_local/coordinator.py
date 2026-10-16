"""Connect to the scale after a weigh-in and read its stored measurements."""

from __future__ import annotations

from dataclasses import dataclass, field
from collections.abc import Callable
from datetime import datetime
import logging
import time

from bleak_retry_connector import BleakClientWithServiceCache, establish_connection
from .withings_wpp.advertisement import WithingsUuid
from .withings_wpp.client import read_measurements
from .withings_wpp.measures import MeasureGroup, merge_by_time

from homeassistant.components import bluetooth
from homeassistant.components.bluetooth import BluetoothScanningMode, BluetoothServiceInfoBleak
from homeassistant.components.bluetooth.active_update_coordinator import (
    ActiveBluetoothDataUpdateCoordinator,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_ADDRESS
from homeassistant.core import CALLBACK_TYPE, HomeAssistant, callback
from homeassistant.util import dt as dt_util

from .const import BODY_SMART_MODEL_ID, CONF_KL, OPT_KNOWN_USERS, POLL_COOLDOWN_SECONDS

_LOGGER = logging.getLogger(__name__)

type WithingsLocalConfigEntry = ConfigEntry[WithingsScaleCoordinator]


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


def latest_per_user(groups: list[MeasureGroup]) -> dict[int, WeighIn]:
    """Each user's newest weigh-in (merged across same-timestamp groups), plus a derived fat ratio.

    User 0 collects weigh-ins the scale couldn't attribute to anyone.
    """
    latest: dict[int, WeighIn] = {}
    for g in merge_by_time(groups):  # oldest first, so later ones win
        values = {m.name: m.value for m in g.measures}
        if (weight := values.get("weight")) and (fat := values.get("fat_mass")) is not None:
            values.setdefault("fat_ratio", round(fat / weight * 100, 2))
        latest[g.user_id] = WeighIn(g.time, values)
    return latest


WITHINGS_COMPANY_ID = 0x03FF


def has_new_data(service_info: BluetoothServiceInfoBleak) -> bool:
    """True when the scale advertises as an installed device (after a weigh-in).

    Two signals, because passive scanners may not receive the scan response:
    - the service UUID tail carries the scale's MAC (all zeros in setup/button sessions);
    - the Withings manufacturer data is non-zero (all zeros in setup sessions).
    """
    for uuid in service_info.service_uuids:
        w = WithingsUuid.parse(uuid)
        if w and w.model_id == BODY_SMART_MODEL_ID and w.tail.strip("0"):
            return True
    mfr = service_info.manufacturer_data.get(WITHINGS_COMPANY_ID)
    return bool(mfr) and any(mfr)


class WithingsScaleCoordinator(ActiveBluetoothDataUpdateCoordinator[ScaleData]):
    """Poll the scale whenever it advertises new measurements."""

    def __init__(self, hass: HomeAssistant, entry: WithingsLocalConfigEntry) -> None:
        self._kl: str = entry.data[CONF_KL]
        self._entry = entry
        self.title = entry.title
        # Users seen so far, in order of first appearance; persisted so their entities exist after a restart.
        self.known_users: list[int] = list(entry.options.get(OPT_KNOWN_USERS, []))
        self._new_user_listeners: list[Callable[[list[int]], None]] = []
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
        new_data = has_new_data(service_info)
        # The cooldown only avoids re-reading after a successful sync; after a failure, retry while
        # the scale is still advertising (its window is short).
        due = (
            seconds_since_last_poll is None
            or seconds_since_last_poll >= POLL_COOLDOWN_SECONDS
            or not self.last_poll_successful
        )
        _LOGGER.debug(
            "%s: advertisement via %s (rssi %s, connectable %s, uuids %d, withings mfr data %s): new data %s, poll due %s",
            self.title,
            service_info.source,
            service_info.rssi,
            service_info.connectable,
            len(service_info.service_uuids),
            "present" if WITHINGS_COMPANY_ID in service_info.manufacturer_data else "absent",
            new_data,
            due,
        )
        return new_data and due

    async def _async_sync(self, service_info: BluetoothServiceInfoBleak) -> ScaleData:
        _LOGGER.info(
            "%s: weigh-in advertised, connecting via %s (rssi %s)", self.title, service_info.source, service_info.rssi
        )
        device = bluetooth.async_ble_device_from_address(self.hass, service_info.address, connectable=True)
        started = time.monotonic()
        step = "connecting"
        try:
            client = await establish_connection(
                BleakClientWithServiceCache, device or service_info.device, self.title, max_attempts=3
            )
            step = "reading"
            _LOGGER.debug("%s: connected after %.1fs", self.title, time.monotonic() - started)
            try:
                result = await read_measurements(client, self._kl)
            finally:
                await client.disconnect()
        except Exception as err:
            # HA's coordinator only logs the first failure in a row; log every one so users can debug range issues.
            _LOGGER.warning(
                "%s: sync failed while %s after %.1fs via %s (rssi %s): %s: %s",
                self.title,
                step,
                time.monotonic() - started,
                service_info.source,
                service_info.rssi,
                type(err).__name__,
                err,
            )
            raise

        if not result.authenticated:
            _LOGGER.debug("%s: session without authentication (button press?), nothing to read", self.title)
            return self.data
        if not result.scale_verified:
            _LOGGER.warning("%s: the scale did not prove it knows the key; check the configured kl", self.title)

        users = dict(self.data.users)
        for user_id, weigh_in in latest_per_user(result.groups).items():
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
            _LOGGER.debug("%s: stored weigh-in %s, user %s, %d values", self.title, g.time, g.user_id, len(g.measures))
        _LOGGER.info(
            "%s: sync done: %d weigh-in(s) stored on the scale, %d user(s)", self.title, len(result.groups), len(users)
        )
        return data
