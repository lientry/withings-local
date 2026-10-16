from datetime import UTC, datetime

from pytest_homeassistant_custom_component.common import MockConfigEntry

from homeassistant.const import STATE_UNAVAILABLE
from homeassistant.core import HomeAssistant

from custom_components.withings_local.const import CONF_KL, DOMAIN
from custom_components.withings_local.coordinator import ScaleData

from .conftest import ADDRESS, TEST_KL


async def test_sensors_follow_coordinator_and_stay_available(hass: HomeAssistant, mock_bluetooth) -> None:
    entry = MockConfigEntry(domain=DOMAIN, unique_id=ADDRESS.lower(), title="Body Smart",
                            data={"address": ADDRESS, CONF_KL: TEST_KL})
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    assert hass.states.get("sensor.body_smart_weight").state == STATE_UNAVAILABLE

    coordinator = entry.runtime_data
    coordinator.data = ScaleData(
        measured_at=datetime(2026, 1, 2, 7, 30, tzinfo=UTC),
        values={"weight": 70.12, "fat_ratio": 20.0, "heart_rate": 60.0},
        last_sync=datetime(2026, 1, 2, 7, 31, tzinfo=UTC),
    )
    coordinator.async_update_listeners()
    await hass.async_block_till_done()

    weight = hass.states.get("sensor.body_smart_weight")
    assert float(weight.state) == 70.12 and weight.attributes["unit_of_measurement"] == "kg"
    assert hass.states.get("sensor.body_smart_fat_ratio").state == "20.0"
    assert hass.states.get("sensor.body_smart_last_weigh_in").state == "2026-01-02T07:30:00+00:00"
    # No reading yet for this one, so it stays unavailable.
    assert hass.states.get("sensor.body_smart_muscle_mass").state == STATE_UNAVAILABLE

    assert await hass.config_entries.async_unload(entry.entry_id)
