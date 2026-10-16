"""Withings Local: read a Withings Body Smart scale over Bluetooth, without the cloud."""

from __future__ import annotations

from homeassistant.const import Platform
from homeassistant.core import HomeAssistant

from .coordinator import WithingsLocalConfigEntry, WithingsScaleCoordinator

PLATFORMS: list[Platform] = [Platform.SENSOR]


async def async_setup_entry(hass: HomeAssistant, entry: WithingsLocalConfigEntry) -> bool:
    """Set up a scale. It only advertises after a weigh-in, so don't require it to be in range now."""
    coordinator = WithingsScaleCoordinator(hass, entry)
    entry.runtime_data = coordinator
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(coordinator.async_start())
    return True


async def async_unload_entry(hass: HomeAssistant, entry: WithingsLocalConfigEntry) -> bool:
    """Unload a config entry."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
