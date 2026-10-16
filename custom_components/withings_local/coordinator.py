"""Connect to the scale after a weigh-in and read its stored measurements."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
import logging

from bleak_retry_connector import BleakClientWithServiceCache, establish_connection
from .withings_wpp.advertisement import WithingsUuid
from .withings_wpp.client import read_measurements
from .withings_wpp.measures import MeasureGroup

from homeassistant.components import bluetooth
from homeassistant.components.bluetooth import BluetoothScanningMode, BluetoothServiceInfoBleak
from homeassistant.components.bluetooth.active_update_coordinator import (
    ActiveBluetoothDataUpdateCoordinator,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_ADDRESS
from homeassistant.core import HomeAssistant, callback
from homeassistant.util import dt as dt_util

from .const import BODY_SMART_MODEL_ID, CONF_KL, POLL_COOLDOWN_SECONDS

_LOGGER = logging.getLogger(__name__)

type WithingsLocalConfigEntry = ConfigEntry[WithingsScaleCoordinator]


@dataclass
class ScaleData:
    """Latest weigh-in read from the scale."""

    measured_at: datetime | None = None
    values: dict[str, float] = field(default_factory=dict)
    user_ids: list[int] = field(default_factory=list)
    firmware: int | None = None
    last_sync: datetime | None = None


def latest_weigh_in(groups: list[MeasureGroup]) -> tuple[datetime, dict[str, float], list[int]] | None:
    """Merge groups sharing the newest timestamp (body composition and heart rate come separately)."""
    if not groups:
        return None
    newest = max(g.time for g in groups)
    values: dict[str, float] = {}
    users: list[int] = []
    for g in groups:
        if g.time == newest:
            values.update({m.name: m.value for m in g.measures})
            users = users or g.user_ids
    if (weight := values.get("weight")) and (fat := values.get("fat_mass")) is not None:
        values.setdefault("fat_ratio", round(fat / weight * 100, 2))
    return newest, values, users


def has_new_data(service_info: BluetoothServiceInfoBleak) -> bool:
    """True when the scale advertises as an installed device (after a weigh-in).

    In setup/button sessions the UUID tail is all zeros and the scale won't hand out measurements.
    """
    for uuid in service_info.service_uuids:
        w = WithingsUuid.parse(uuid)
        if w and w.model_id == BODY_SMART_MODEL_ID and w.tail.strip("0"):
            return True
    return False


class WithingsScaleCoordinator(ActiveBluetoothDataUpdateCoordinator[ScaleData]):
    """Poll the scale whenever it advertises new measurements."""

    def __init__(self, hass: HomeAssistant, entry: WithingsLocalConfigEntry) -> None:
        self._kl: str = entry.data[CONF_KL]
        self.title = entry.title
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
    def _needs_poll(self, service_info: BluetoothServiceInfoBleak, seconds_since_last_poll: float | None) -> bool:
        if not has_new_data(service_info):
            return False
        return seconds_since_last_poll is None or seconds_since_last_poll >= POLL_COOLDOWN_SECONDS

    async def _async_sync(self, service_info: BluetoothServiceInfoBleak) -> ScaleData:
        device = bluetooth.async_ble_device_from_address(self.hass, service_info.address, connectable=True)
        client = await establish_connection(
            BleakClientWithServiceCache, device or service_info.device, self.title, max_attempts=3
        )
        try:
            result = await read_measurements(client, self._kl)
        finally:
            await client.disconnect()

        if not result.authenticated:
            _LOGGER.debug("%s: session without authentication (button press?), nothing to read", self.title)
            return self.data
        if not result.scale_verified:
            _LOGGER.warning("%s: the scale did not prove it knows the key; check the configured kl", self.title)

        data = ScaleData(
            measured_at=self.data.measured_at,
            values=self.data.values,
            user_ids=self.data.user_ids,
            firmware=result.firmware or self.data.firmware,
            last_sync=dt_util.utcnow(),
        )
        if (latest := latest_weigh_in(result.groups)) and (
            data.measured_at is None or latest[0] >= data.measured_at
        ):
            data.measured_at, data.values, data.user_ids = latest
        _LOGGER.debug("%s: read %d group(s), latest %s", self.title, len(result.groups), data.measured_at)
        return data
