"""Fixtures for the Home Assistant integration tests. All values are synthetic."""

import time

import pytest
from bleak.backends.device import BLEDevice
from bleak.backends.scanner import AdvertisementData

from homeassistant.components.bluetooth import BluetoothServiceInfoBleak

ADDRESS = "00:11:22:33:44:55"
INSTALLED_UUID = "00000020-5749-5448-0010-001122334455"  # tail = MAC: installed, has data
SETUP_UUID = "00000020-5749-5448-0010-000000000000"  # tail zeros: button/setup session
TEST_KL = "test-kl-not-a-real-secret-000000"
FD77 = "0000fd77-0000-1000-8000-00805f9b34fb"
BEAMO_SERVICE = "00000000-0000-5749-5448-494e47530000"
# FD77 data as reported for a BeamO (model 71), with a synthetic MAC and field 3.
BEAMO_INSTALLED = bytes.fromhex("1047 1101 34aabbccdd")
BEAMO_SYNC_REQUESTED = bytes.fromhex("1047 1103 34aabbccdd")
BEAMO_SETUP = bytes.fromhex("1047 1100 26001122334455")


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations):
    yield


def service_info(
    name="Body Smart 55", uuid=INSTALLED_UUID, address=ADDRESS, mfr=b"\x01\x02\x03\x04", service_data=None
) -> BluetoothServiceInfoBleak:
    uuids = [uuid] if uuid else []
    service_data = service_data or {}
    adv = AdvertisementData(
        local_name=name,
        manufacturer_data={0x03FF: mfr} if mfr is not None else {},
        service_data=service_data,
        service_uuids=uuids,
        tx_power=0,
        rssi=-60,
        platform_data=(),
    )
    return BluetoothServiceInfoBleak(
        name=name,
        address=address,
        rssi=-60,
        manufacturer_data=adv.manufacturer_data,
        service_data=service_data,
        service_uuids=uuids,
        source="local",
        device=BLEDevice(address, name, {}),
        advertisement=adv,
        connectable=True,
        time=time.monotonic(),
        tx_power=0,
    )


def beamo_info(fd77: bytes = BEAMO_INSTALLED, name=ADDRESS) -> BluetoothServiceInfoBleak:
    """A BeamO advertisement: the newer service UUID (no model in it) and FD77 data. Without a
    local name HA reports the address as the name."""
    return service_info(name=name, uuid=BEAMO_SERVICE, mfr=None, service_data={FD77: fd77})
