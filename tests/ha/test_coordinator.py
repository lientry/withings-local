from datetime import UTC, datetime

from custom_components.withings_local.withings_wpp.measures import Measure, MeasureGroup

from custom_components.withings_local.coordinator import has_new_data, latest_weigh_in

from .conftest import SETUP_UUID, service_info


def test_has_new_data_only_for_installed_advert() -> None:
    assert has_new_data(service_info())
    assert not has_new_data(service_info(uuid=SETUP_UUID))


def test_latest_weigh_in_merges_same_timestamp_and_adds_fat_ratio() -> None:
    # The scale re-sends its whole store; duplicates of a group must collapse.
    old, new = datetime(2026, 1, 1, tzinfo=UTC), datetime(2026, 1, 2, tzinfo=UTC)
    groups = [
        MeasureGroup(old, [1], 0, 0, [Measure(1, 80.0)]),
        MeasureGroup(new, [1], 0, 0, [Measure(1, 70.0), Measure(8, 14.0)]),
        MeasureGroup(new, [1], 0, 0, [Measure(11, 60.0)]),
        MeasureGroup(new, [1], 0, 0, [Measure(1, 70.0)]),
    ]
    when, values = latest_weigh_in(groups)
    assert when == new
    assert values == {"weight": 70.0, "fat_mass": 14.0, "heart_rate": 60.0, "fat_ratio": 20.0}
    assert latest_weigh_in([]) is None
