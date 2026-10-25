import asyncio
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.withings_local.const import CONF_KL, DOMAIN
from custom_components.withings_local.coordinator import (
    WithingsScaleCoordinator,
    has_new_data,
    latest_per_user,
)
from custom_components.withings_local.withings_wpp.client import SyncResult
from custom_components.withings_local.withings_wpp.measures import Measure, MeasureGroup

from .conftest import ADDRESS, SETUP_UUID, TEST_KL, service_info

ALICE, BOB = 1001, 1002  # synthetic user IDs


def test_has_new_data_only_for_installed_advert() -> None:
    assert has_new_data(service_info())
    assert not has_new_data(service_info(uuid=SETUP_UUID, mfr=b"\x00\x00\x00\x00"))


def test_has_new_data_from_manufacturer_data_alone() -> None:
    # Passive scanners may miss the scan response that carries the service UUID.
    assert has_new_data(service_info(uuid=None, mfr=b"\x12\x34\x56\x78"))
    assert not has_new_data(service_info(uuid=None, mfr=b"\x00\x00\x00\x00"))
    assert not has_new_data(service_info(uuid=None, mfr=None))


def test_latest_per_user_merges_and_separates_users() -> None:
    t1, t2, t3 = (datetime(2026, 1, d, tzinfo=UTC) for d in (1, 2, 3))
    groups = [
        MeasureGroup(t1, [ALICE], 0, 0, [Measure(1, 80.0)]),
        MeasureGroup(t2, [ALICE], 0, 0, [Measure(1, 70.0), Measure(8, 14.0)]),
        MeasureGroup(t2, [ALICE], 0, 0, [Measure(11, 60.0)]),  # heart rate arrives as its own group
        MeasureGroup(t2, [ALICE], 0, 0, [Measure(1, 70.0)]),  # the whole store is re-sent every sync
        MeasureGroup(t3, [BOB], 0, 0, [Measure(1, 90.0)]),
        MeasureGroup(t3, [], 0, 0, [Measure(1, 55.0)]),  # guest: no user ID
    ]
    latest = latest_per_user(groups)
    assert set(latest) == {ALICE, BOB, 0}
    assert latest[ALICE].measured_at == t2
    assert latest[ALICE].values == {"weight": 70.0, "fat_mass": 14.0, "heart_rate": 60.0, "fat_ratio": 20.0}
    assert latest[BOB].values == {"weight": 90.0}
    assert latest[0].values == {"weight": 55.0}
    assert latest_per_user([]) == {}


async def test_retries_during_window_after_failure(hass, mock_bluetooth) -> None:
    from pytest_homeassistant_custom_component.common import MockConfigEntry

    from custom_components.withings_local.const import CONF_KL, DOMAIN
    from custom_components.withings_local.coordinator import WithingsScaleCoordinator

    from .conftest import ADDRESS, TEST_KL

    entry = MockConfigEntry(domain=DOMAIN, title="Body Smart", data={"address": ADDRESS, CONF_KL: TEST_KL})
    coordinator = WithingsScaleCoordinator(hass, entry)
    info = service_info()
    assert coordinator._needs_poll(info, None)  # noqa: SLF001
    assert not coordinator._needs_poll(info, 5)  # noqa: SLF001 - recent successful sync: wait
    coordinator.last_poll_successful = False
    assert coordinator._needs_poll(info, 5)  # noqa: SLF001 - recent failure: retry now



def test_setup_mode_detected_despite_merged_weigh_in_data() -> None:
    from custom_components.withings_local.coordinator import is_setup_mode

    from .conftest import INSTALLED_UUID

    merged = service_info(uuid=SETUP_UUID, mfr=b"\x12\x34\x56\x78")  # stale weigh-in bytes
    merged.service_uuids.append(INSTALLED_UUID)  # stale weigh-in UUID
    assert is_setup_mode(merged)
    assert not is_setup_mode(service_info())  # only a weigh-in advertisement


async def test_sync_ignores_readings_from_unverified_scale(hass, mock_bluetooth) -> None:
    """The device fails our challenge: nothing is recorded."""
    entry = MockConfigEntry(domain=DOMAIN, title="Body Smart", data={"address": ADDRESS, CONF_KL: TEST_KL})
    entry.add_to_hass(hass)  # a successful sync stores the users it saw on the entry
    coordinator = WithingsScaleCoordinator(hass, entry)
    when = datetime(2026, 1, 2, tzinfo=UTC)
    group = MeasureGroup(when, [ALICE], 0, 0, [Measure(1, 70.0)])

    def result(verified: bool) -> SyncResult:
        return SyncResult(True, verified, 2, 1311, [group], battery=80)

    client = MagicMock(disconnect=AsyncMock())
    with (
        patch("custom_components.withings_local.coordinator.establish_connection", AsyncMock(return_value=client)),
        patch("custom_components.withings_local.coordinator.WppSession"),
        patch("custom_components.withings_local.coordinator.read_measurements", AsyncMock(return_value=result(False))),
    ):
        data = await coordinator._async_sync(service_info())  # noqa: SLF001
    assert data.users == {} and data.battery is None and data.last_sync is None

    with (
        patch("custom_components.withings_local.coordinator.establish_connection", AsyncMock(return_value=client)),
        patch("custom_components.withings_local.coordinator.WppSession"),
        patch("custom_components.withings_local.coordinator.read_measurements", AsyncMock(return_value=result(True))),
    ):
        data = await coordinator._async_sync(service_info())  # noqa: SLF001
    assert data.users[ALICE].values == {"weight": 70.0} and data.battery == 80


def test_beamo_new_data_and_sync_request_from_fd77() -> None:
    from custom_components.withings_local.coordinator import (
        ready_to_pair,
        sync_requested,
    )
    from custom_components.withings_local.withings_wpp.devices import BEAMO

    from .conftest import BEAMO_SETUP, BEAMO_SYNC_REQUESTED, beamo_info

    assert has_new_data(beamo_info(), BEAMO) and not sync_requested(beamo_info(), BEAMO)
    assert has_new_data(beamo_info(BEAMO_SYNC_REQUESTED), BEAMO) and sync_requested(beamo_info(BEAMO_SYNC_REQUESTED), BEAMO)
    assert not has_new_data(beamo_info(BEAMO_SETUP), BEAMO)
    assert ready_to_pair(beamo_info(), BEAMO)
    assert not has_new_data(service_info(), BEAMO)  # a Body Smart advertisement isn't a BeamO's
    assert not has_new_data(beamo_info())  # nor the other way round


async def test_beamo_polls_at_once_only_when_asked(hass, mock_bluetooth) -> None:
    from .conftest import BEAMO_SYNC_REQUESTED, beamo_info

    entry = MockConfigEntry(domain=DOMAIN, title="BeamO", data={"address": ADDRESS, CONF_KL: TEST_KL, "model": 71})
    coordinator = WithingsScaleCoordinator(hass, entry)

    def needs_poll(info, age):  # each check on its own: no poll left pending from the previous one
        coordinator._poll_scheduled_since = None  # noqa: SLF001
        return coordinator._needs_poll(info, age)  # noqa: SLF001

    assert needs_poll(beamo_info(), None)  # first sight: look
    assert not needs_poll(beamo_info(), 60)  # idle: wait IDLE_POLL_SECONDS
    assert needs_poll(beamo_info(), 301)
    assert needs_poll(beamo_info(BEAMO_SYNC_REQUESTED), 60)  # it asks: go


async def test_beamo_failed_idle_poll_doesnt_retry_at_once(hass, mock_bluetooth) -> None:
    from .conftest import BEAMO_SYNC_REQUESTED, beamo_info

    entry = MockConfigEntry(domain=DOMAIN, title="BeamO", data={"address": ADDRESS, CONF_KL: TEST_KL, "model": 71})
    coordinator = WithingsScaleCoordinator(hass, entry)

    def needs_poll(info, age):  # each check on its own: no poll left pending from the previous one
        coordinator._poll_scheduled_since = None  # noqa: SLF001
        return coordinator._needs_poll(info, age)  # noqa: SLF001

    coordinator.last_poll_successful = False
    assert not needs_poll(beamo_info(), 10)  # idle: wait before retrying
    assert needs_poll(beamo_info(), 31)
    assert needs_poll(beamo_info(BEAMO_SYNC_REQUESTED), 10)  # it asks: retry now


async def test_beamo_hears_unchanged_advertisements(hass, mock_bluetooth) -> None:
    """HA's change-only callbacks would never report the same BeamO advertisement again."""
    from .conftest import beamo_info

    registered = []

    def fake_register(hass, callback, address):
        registered.append(callback)
        return lambda: registered.remove(callback)

    entry = MockConfigEntry(domain=DOMAIN, title="BeamO", data={"address": ADDRESS, CONF_KL: TEST_KL, "model": 71})
    coordinator = WithingsScaleCoordinator(hass, entry)
    with (
        patch("custom_components.withings_local.coordinator.bluetooth.async_register_advertisement_callback", fake_register),
        patch.object(coordinator, "_async_handle_bluetooth_event") as handle,
    ):
        stop = coordinator.async_start()
        (on_advertisement,) = registered
        on_advertisement(beamo_info())
        on_advertisement(beamo_info())
        assert handle.call_count == 2
        stop()
    assert registered == []


async def test_body_smart_keeps_change_only_callbacks(hass, mock_bluetooth) -> None:
    entry = MockConfigEntry(domain=DOMAIN, title="Body Smart", data={"address": ADDRESS, CONF_KL: TEST_KL})
    coordinator = WithingsScaleCoordinator(hass, entry)
    with patch("custom_components.withings_local.coordinator.bluetooth.async_register_advertisement_callback") as register:
        coordinator.async_start()()
    register.assert_not_called()


def test_latest_reading_with_the_required_value_wins() -> None:
    t1, t2 = datetime(2026, 1, 1, tzinfo=UTC), datetime(2026, 1, 2, tzinfo=UTC)
    groups = [
        MeasureGroup(t1, [ALICE], 0, 0, [Measure(71, 36.7)]),
        MeasureGroup(t2, [ALICE], 0, 0, [Measure(11, 60.0)]),  # a newer reading of another kind
    ]
    assert latest_per_user(groups, "body_temperature")[ALICE].values == {"body_temperature": 36.7}
    assert latest_per_user(groups)[ALICE].measured_at == t2  # unchanged for the scale


async def test_beamo_doesnt_queue_a_second_poll(hass, mock_bluetooth) -> None:
    """HA's debouncer would run a poll asked for during another one, skipping the cooldowns."""
    from .conftest import BEAMO_SYNC_REQUESTED, beamo_info

    entry = MockConfigEntry(domain=DOMAIN, title="BeamO", data={"address": ADDRESS, CONF_KL: TEST_KL, "model": 71})
    coordinator = WithingsScaleCoordinator(hass, entry)
    info = beamo_info(BEAMO_SYNC_REQUESTED)
    assert coordinator._needs_poll(info, None)  # noqa: SLF001
    assert not coordinator._needs_poll(info, None)  # noqa: SLF001 - the same advertisement via the other callback
    with patch.object(coordinator, "_async_read", AsyncMock(return_value=coordinator.data)):
        await coordinator._async_sync(info)  # noqa: SLF001
    assert coordinator._needs_poll(info, 31)  # noqa: SLF001 - finished: the cooldowns apply again


async def test_beamo_running_poll_blocks_others_however_long_it_takes(hass, mock_bluetooth) -> None:
    from .conftest import BEAMO_SYNC_REQUESTED, beamo_info

    entry = MockConfigEntry(domain=DOMAIN, title="BeamO", data={"address": ADDRESS, CONF_KL: TEST_KL, "model": 71})
    coordinator = WithingsScaleCoordinator(hass, entry)
    info = beamo_info(BEAMO_SYNC_REQUESTED)
    assert coordinator._needs_poll(info, None)  # noqa: SLF001
    started, release = asyncio.Event(), asyncio.Event()

    async def slow_read(_info):
        started.set()
        await release.wait()
        return coordinator.data

    with patch.object(coordinator, "_async_read", slow_read):
        task = hass.async_create_task(coordinator._async_sync(info))  # noqa: SLF001
        await started.wait()
        # The scheduled mark is gone once the poll starts; only "running" holds it back now.
        assert coordinator._poll_scheduled_since is None  # noqa: SLF001
        assert not coordinator._needs_poll(info, 500)  # noqa: SLF001
        release.set()
        await task
    assert coordinator._needs_poll(info, 31)  # noqa: SLF001
