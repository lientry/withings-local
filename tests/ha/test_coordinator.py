from datetime import UTC, datetime

from custom_components.withings_local.coordinator import has_new_data, latest_per_user
from custom_components.withings_local.withings_wpp.measures import Measure, MeasureGroup

from .conftest import SETUP_UUID, service_info

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
