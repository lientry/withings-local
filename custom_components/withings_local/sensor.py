"""Measurement sensors for the latest weigh-in."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime

from homeassistant.components.sensor import (
    RestoreSensor,
    SensorDeviceClass,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import PERCENTAGE, EntityCategory, UnitOfEnergy, UnitOfMass, UnitOfTime
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.device_registry import CONNECTION_BLUETOOTH, DeviceInfo
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .const import DOMAIN
from .coordinator import ScaleData, WithingsLocalConfigEntry, WithingsScaleCoordinator


@dataclass(frozen=True, kw_only=True)
class WithingsSensorDescription(SensorEntityDescription):
    value_fn: Callable[[ScaleData], float | datetime | None]


def _measure(name: str) -> Callable[[ScaleData], float | None]:
    return lambda data: data.values.get(name)


def _mass(key: str, precision: int = 2, enabled: bool = True) -> WithingsSensorDescription:
    return WithingsSensorDescription(
        key=key,
        translation_key=key,
        device_class=SensorDeviceClass.WEIGHT,
        native_unit_of_measurement=UnitOfMass.KILOGRAMS,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=precision,
        entity_registry_enabled_default=enabled,
        value_fn=_measure(key),
    )


SENSORS: tuple[WithingsSensorDescription, ...] = (
    _mass("weight"),
    _mass("fat_mass"),
    _mass("fat_free_mass"),
    _mass("muscle_mass"),
    _mass("bone_mass"),
    _mass("hydration"),
    WithingsSensorDescription(
        key="fat_ratio",
        translation_key="fat_ratio",
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=1,
        value_fn=_measure("fat_ratio"),
    ),
    WithingsSensorDescription(
        key="visceral_fat",
        translation_key="visceral_fat",
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=1,
        value_fn=_measure("visceral_fat"),
    ),
    WithingsSensorDescription(
        key="basal_metabolic_rate",
        translation_key="basal_metabolic_rate",
        native_unit_of_measurement=UnitOfEnergy.KILO_CALORIE,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=0,
        value_fn=_measure("basal_metabolic_rate"),
    ),
    WithingsSensorDescription(
        key="metabolic_age",
        translation_key="metabolic_age",
        native_unit_of_measurement=UnitOfTime.YEARS,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=0,
        value_fn=_measure("metabolic_age"),
    ),
    WithingsSensorDescription(
        key="heart_rate",
        translation_key="heart_rate",
        native_unit_of_measurement="bpm",
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=0,
        value_fn=_measure("heart_rate"),
    ),
    WithingsSensorDescription(
        key="measured_at",
        translation_key="measured_at",
        device_class=SensorDeviceClass.TIMESTAMP,
        value_fn=lambda data: data.measured_at,
    ),
    WithingsSensorDescription(
        key="last_sync",
        translation_key="last_sync",
        device_class=SensorDeviceClass.TIMESTAMP,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda data: data.last_sync,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant, entry: WithingsLocalConfigEntry, async_add_entities: AddConfigEntryEntitiesCallback
) -> None:
    coordinator = entry.runtime_data
    async_add_entities(WithingsScaleSensor(coordinator, description) for description in SENSORS)


class WithingsScaleSensor(RestoreSensor):
    """A value from the latest weigh-in.

    The scale only advertises right after a weigh-in, so availability follows "do we have a
    value", not Bluetooth presence. Values survive restarts.
    """

    _attr_has_entity_name = True
    _attr_should_poll = False
    entity_description: WithingsSensorDescription

    def __init__(self, coordinator: WithingsScaleCoordinator, description: WithingsSensorDescription) -> None:
        self.coordinator = coordinator
        self.entity_description = description
        address = coordinator.address
        self._attr_unique_id = f"{address}-{description.key}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, address)},
            connections={(CONNECTION_BLUETOOTH, address)},
            name=coordinator.title,
            manufacturer="Withings",
            model="Body Smart",
            model_id="WBS13",
        )

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        if (last := await self.async_get_last_sensor_data()) is not None:
            self._attr_native_value = last.native_value
        self._update_from_coordinator()
        self.async_on_remove(self.coordinator.async_add_listener(self._handle_coordinator_update))

    @callback
    def _handle_coordinator_update(self) -> None:
        self._update_from_coordinator()
        self.async_write_ha_state()

    def _update_from_coordinator(self) -> None:
        value = self.entity_description.value_fn(self.coordinator.data)
        if value is not None:
            self._attr_native_value = value

    @property
    def available(self) -> bool:
        return self._attr_native_value is not None
