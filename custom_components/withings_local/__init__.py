"""Withings Local: read a Withings Body Smart scale over Bluetooth, without the cloud."""

from __future__ import annotations

from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er

from .coordinator import WithingsLocalConfigEntry, WithingsScaleCoordinator

PLATFORMS: list[Platform] = [Platform.SENSOR]


async def async_setup_entry(hass: HomeAssistant, entry: WithingsLocalConfigEntry) -> bool:
    """Set up a scale. It only advertises after a weigh-in, so don't require it to be in range now."""
    _remove_single_user_entities(hass, entry)
    coordinator = WithingsScaleCoordinator(hass, entry)
    entry.runtime_data = coordinator
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(coordinator.async_start())
    return True


async def async_unload_entry(hass: HomeAssistant, entry: WithingsLocalConfigEntry) -> bool:
    """Unload a config entry."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)


# Keys whose sensors moved from the scale device to per-user devices in 0.2.0.
_PER_USER_KEYS = {
    "weight", "fat_mass", "fat_free_mass", "muscle_mass", "bone_mass", "hydration", "fat_ratio",
    "visceral_fat", "basal_metabolic_rate", "metabolic_age", "heart_rate", "measured_at",
}


def _remove_single_user_entities(hass: HomeAssistant, entry: WithingsLocalConfigEntry) -> None:
    """Drop entities from the single-user version (unique id `<address>-<key>`)."""
    registry = er.async_get(hass)
    address = entry.data["address"]
    for ent in er.async_entries_for_config_entry(registry, entry.entry_id):
        if ent.unique_id in {f"{address}-{key}" for key in _PER_USER_KEYS}:
            registry.async_remove(ent.entity_id)
