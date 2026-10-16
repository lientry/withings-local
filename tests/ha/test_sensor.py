from datetime import UTC, datetime

from pytest_homeassistant_custom_component.common import MockConfigEntry

from homeassistant.const import STATE_UNAVAILABLE
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er

from custom_components.withings_local.const import CONF_KL, CONF_USERS, DOMAIN, OPT_KNOWN_USERS
from custom_components.withings_local.coordinator import ScaleData, WeighIn

from .conftest import ADDRESS, TEST_KL

ALICE, BOB = 1001, 1002  # synthetic user IDs


async def _setup(hass: HomeAssistant, **entry_kwargs) -> MockConfigEntry:
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id=ADDRESS.lower(),
        title="Body Smart",
        data={"address": ADDRESS, CONF_KL: TEST_KL, **entry_kwargs.pop("data", {})},
        **entry_kwargs,
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry


def _sync(entry, users: dict[int, WeighIn], battery=80) -> None:
    coordinator = entry.runtime_data
    coordinator.data = ScaleData(users=users, battery=battery, last_sync=datetime(2026, 1, 2, 8, tzinfo=UTC))
    coordinator._register_users(list(users))  # noqa: SLF001 - what a real sync does
    coordinator.async_update_listeners()


async def test_per_user_sensors_appear_and_keep_values(hass: HomeAssistant, mock_bluetooth) -> None:
    entry = await _setup(hass, data={CONF_USERS: {str(ALICE): "Alice"}})
    assert hass.states.get("sensor.body_smart_battery").state == STATE_UNAVAILABLE
    assert hass.states.get("sensor.body_smart_alice_weight") is None  # no users seen yet

    when = datetime(2026, 1, 2, 7, 30, tzinfo=UTC)
    _sync(entry, {ALICE: WeighIn(when, {"weight": 70.12, "fat_ratio": 20.0}), BOB: WeighIn(when, {"weight": 90.0})})
    await hass.async_block_till_done()

    alice = hass.states.get("sensor.body_smart_alice_weight")
    assert float(alice.state) == 70.12 and alice.attributes["unit_of_measurement"] == "kg"
    assert hass.states.get("sensor.body_smart_alice_fat_ratio").state == "20.0"
    assert hass.states.get("sensor.body_smart_alice_last_weigh_in").state == "2026-01-02T07:30:00+00:00"
    assert float(hass.states.get("sensor.body_smart_user_2_weight").state) == 90.0  # no name known
    assert hass.states.get("sensor.body_smart_user_2_muscle_mass").state == STATE_UNAVAILABLE
    assert hass.states.get("sensor.body_smart_battery").state == "80"
    assert entry.options[OPT_KNOWN_USERS] == [ALICE, BOB]

    from custom_components.withings_local.diagnostics import async_get_config_entry_diagnostics

    diag = await async_get_config_entry_diagnostics(hass, entry)
    assert TEST_KL not in str(diag) and ADDRESS not in str(diag) and "Alice" not in str(diag)
    assert str(ALICE) not in str(diag)
    assert [u["measurement_types"] for u in diag["users"]] == [["fat_ratio", "weight"], ["weight"]]

    assert await hass.config_entries.async_unload(entry.entry_id)


async def test_guest_gets_weight_only_and_isnt_numbered(hass: HomeAssistant, mock_bluetooth) -> None:
    entry = await _setup(hass)
    when = datetime(2026, 1, 2, tzinfo=UTC)
    _sync(entry, {ALICE: WeighIn(when, {"weight": 70.0}), 0: WeighIn(when, {"weight": 55.0}), BOB: WeighIn(when, {"weight": 90.0})})
    await hass.async_block_till_done()
    assert float(hass.states.get("sensor.body_smart_guest_weight").state) == 55.0
    assert hass.states.get("sensor.body_smart_guest_muscle_mass") is None
    # Guest doesn't take a number: the second real user is "User 2", not "User 3".
    assert float(hass.states.get("sensor.body_smart_user_2_weight").state) == 90.0
    assert await hass.config_entries.async_unload(entry.entry_id)


async def test_known_users_restored_and_old_entities_removed(hass: HomeAssistant, mock_bluetooth) -> None:
    registry = er.async_get(hass)
    entry = MockConfigEntry(
        domain=DOMAIN, unique_id=ADDRESS.lower(), title="Body Smart",
        data={"address": ADDRESS, CONF_KL: TEST_KL}, options={OPT_KNOWN_USERS: [ALICE]},
    )
    entry.add_to_hass(hass)
    old = registry.async_get_or_create("sensor", DOMAIN, f"{ADDRESS}-weight", config_entry=entry)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert registry.async_get(old.entity_id) is None
    # Users seen before a restart get their entities straight away.
    assert hass.states.get("sensor.body_smart_user_1_weight") is not None
    assert await hass.config_entries.async_unload(entry.entry_id)
