"""Sensor platform for Daze: per-socket telemetry, per-EVSE diagnostics, per-network tariff."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import (
    EntityCategory,
    UnitOfElectricCurrent,
    UnitOfElectricPotential,
    UnitOfEnergy,
    UnitOfPower,
    UnitOfTemperature,
    UnitOfTime,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.typing import StateType
from homeassistant.util import dt as dt_util

from .const import (
    CHARGE_COMMAND_LABELS,
    DOMAIN,
    EVSE_STATE_LABELS,
    EVSE_SYSTEM_ERROR_LABELS,
)
from .coordinator import DazeCoordinator
from .entity import (
    DazeEvseEntity,
    DazeNetworkEntity,
    DazeSocketEntity,
    evse_device_info,
    network_device_info,
    socket_device_info,
)
from .models import DazeEvse, DazeNetwork, DazeSocket


def _ma_to_a(value: int | None) -> float | None:
    return value / 1000 if value is not None else None


def _wh_to_kwh(value: int | None) -> float | None:
    return value / 1000 if value is not None else None


def _charge_time_to_minutes(value: str | None) -> float | None:
    """Session chargeTime arrives as "HH:MM:SS"; hours are not wrapped at 24."""
    if not value:
        return None
    parts = value.split(":")
    if len(parts) != 3 or not all(part.isdigit() for part in parts):
        return None
    hours, minutes, seconds = (int(part) for part in parts)
    return round(hours * 60 + minutes + seconds / 60, 1)


def _iso_to_datetime(value: str | None) -> datetime | None:
    """Session startTime arrives as an ISO string; timestamp sensors want a datetime."""
    return dt_util.parse_datetime(value) if value else None


@dataclass(frozen=True, kw_only=True)
class DazeSocketSensorEntityDescription(SensorEntityDescription):
    value_fn: Callable[[DazeSocket], StateType | datetime]
    requires_three_phase: bool = False


@dataclass(frozen=True, kw_only=True)
class DazeEvseSensorEntityDescription(SensorEntityDescription):
    value_fn: Callable[[DazeEvse], StateType]
    requires_three_phase: bool = False


SOCKET_SENSOR_DESCRIPTIONS: tuple[DazeSocketSensorEntityDescription, ...] = (
    DazeSocketSensorEntityDescription(
        key="power",
        translation_key="power",
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfPower.WATT,
        value_fn=lambda s: s.last_power,
    ),
    DazeSocketSensorEntityDescription(
        key="session_energy",
        translation_key="session_energy",
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL_INCREASING,
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        suggested_display_precision=2,
        value_fn=lambda s: _wh_to_kwh(s.last_energy),
    ),
    DazeSocketSensorEntityDescription(
        key="charging_current_l1",
        translation_key="charging_current_l1",
        device_class=SensorDeviceClass.CURRENT,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfElectricCurrent.AMPERE,
        value_fn=lambda s: _ma_to_a(s.last_charging_current_l1),
    ),
    DazeSocketSensorEntityDescription(
        key="charging_current_l2",
        translation_key="charging_current_l2",
        device_class=SensorDeviceClass.CURRENT,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfElectricCurrent.AMPERE,
        value_fn=lambda s: _ma_to_a(s.last_charging_current_l2),
        requires_three_phase=True,
    ),
    DazeSocketSensorEntityDescription(
        key="charging_current_l3",
        translation_key="charging_current_l3",
        device_class=SensorDeviceClass.CURRENT,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfElectricCurrent.AMPERE,
        value_fn=lambda s: _ma_to_a(s.last_charging_current_l3),
        requires_three_phase=True,
    ),
    DazeSocketSensorEntityDescription(
        key="voltage_l1",
        translation_key="voltage_l1",
        device_class=SensorDeviceClass.VOLTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        value_fn=lambda s: s.last_ac_voltage_l1,
    ),
    DazeSocketSensorEntityDescription(
        key="voltage_l2",
        translation_key="voltage_l2",
        device_class=SensorDeviceClass.VOLTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        value_fn=lambda s: s.last_ac_voltage_l2,
        requires_three_phase=True,
    ),
    DazeSocketSensorEntityDescription(
        key="voltage_l3",
        translation_key="voltage_l3",
        device_class=SensorDeviceClass.VOLTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        value_fn=lambda s: s.last_ac_voltage_l3,
        requires_three_phase=True,
    ),
    DazeSocketSensorEntityDescription(
        key="board_temperature",
        translation_key="board_temperature",
        device_class=SensorDeviceClass.TEMPERATURE,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda s: s.last_board_temperature,
    ),
    DazeSocketSensorEntityDescription(
        key="case_temperature",
        translation_key="case_temperature",
        device_class=SensorDeviceClass.TEMPERATURE,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda s: s.last_case_temperature,
    ),
    DazeSocketSensorEntityDescription(
        key="max_charging_current",
        translation_key="max_charging_current",
        device_class=SensorDeviceClass.CURRENT,
        native_unit_of_measurement=UnitOfElectricCurrent.AMPERE,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda s: _ma_to_a(s.last_max_charging_current),
    ),
    # lastStatus (from /evses) and evseState (from /sockets/{serial}/remoteInfo) are the
    # same underlying EVSE state enum, polled via two different endpoints - kept as two
    # separate sensors since they can momentarily disagree between poll cycles.
    DazeSocketSensorEntityDescription(
        key="status",
        translation_key="status",
        device_class=SensorDeviceClass.ENUM,
        options=list(EVSE_STATE_LABELS.values()),
        value_fn=lambda s: EVSE_STATE_LABELS.get(s.last_status),
    ),
    DazeSocketSensorEntityDescription(
        key="evse_state",
        translation_key="evse_state",
        device_class=SensorDeviceClass.ENUM,
        options=list(EVSE_STATE_LABELS.values()),
        value_fn=lambda s: EVSE_STATE_LABELS.get(s.evse_state),
    ),
    DazeSocketSensorEntityDescription(
        key="system_error",
        translation_key="system_error",
        device_class=SensorDeviceClass.ENUM,
        options=list(EVSE_SYSTEM_ERROR_LABELS.values()),
        value_fn=lambda s: EVSE_SYSTEM_ERROR_LABELS.get(s.evse_system_error),
    ),
    DazeSocketSensorEntityDescription(
        key="fan_status",
        translation_key="fan_status",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda s: s.last_fan_status,
    ),
    # Which charge command the socket currently accepts (see CHARGE_COMMAND_LABELS).
    # The charging switch drives off this, so it is worth being able to see it.
    DazeSocketSensorEntityDescription(
        key="available_charge_command",
        translation_key="available_charge_command",
        device_class=SensorDeviceClass.ENUM,
        options=list(CHARGE_COMMAND_LABELS.values()),
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda s: CHARGE_COMMAND_LABELS.get(s.available_charge_command),
    ),
    # --- Charging session (chargeSession object inside remoteInfo) ---
    # session_id changes exactly once per charge and goes back to unknown when the
    # wallbox closes the session, so an automation triggering on it can log one row per
    # charge without guessing where one ended and the next began.
    DazeSocketSensorEntityDescription(
        key="session_id",
        translation_key="session_id",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda s: s.session_id,
    ),
    DazeSocketSensorEntityDescription(
        key="session_start",
        translation_key="session_start",
        device_class=SensorDeviceClass.TIMESTAMP,
        value_fn=lambda s: _iso_to_datetime(s.session_start_time),
    ),
    DazeSocketSensorEntityDescription(
        key="session_duration",
        translation_key="session_duration",
        device_class=SensorDeviceClass.DURATION,
        native_unit_of_measurement=UnitOfTime.MINUTES,
        suggested_display_precision=0,
        value_fn=lambda s: _charge_time_to_minutes(s.session_charge_time),
    ),
    DazeSocketSensorEntityDescription(
        key="session_user",
        translation_key="session_user",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda s: s.session_user_name,
    ),
)

EVSE_SENSOR_DESCRIPTIONS: tuple[DazeEvseSensorEntityDescription, ...] = (
    DazeEvseSensorEntityDescription(
        key="wifi_ssid",
        translation_key="wifi_ssid",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda e: e.wifi_ssid,
    ),
    DazeEvseSensorEntityDescription(
        key="software_version",
        translation_key="software_version",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda e: e.software_version,
    ),
    DazeEvseSensorEntityDescription(
        key="firmware_version",
        translation_key="firmware_version",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda e: e.firmware_version,
    ),
    DazeEvseSensorEntityDescription(
        key="grid_current_l1",
        translation_key="grid_current_l1",
        device_class=SensorDeviceClass.CURRENT,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfElectricCurrent.AMPERE,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda e: _ma_to_a(e.last_supply_grid_instant_current_l1),
    ),
    DazeEvseSensorEntityDescription(
        key="grid_current_l2",
        translation_key="grid_current_l2",
        device_class=SensorDeviceClass.CURRENT,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfElectricCurrent.AMPERE,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda e: _ma_to_a(e.last_supply_grid_instant_current_l2),
        requires_three_phase=True,
    ),
    DazeEvseSensorEntityDescription(
        key="grid_current_l3",
        translation_key="grid_current_l3",
        device_class=SensorDeviceClass.CURRENT,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfElectricCurrent.AMPERE,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda e: _ma_to_a(e.last_supply_grid_instant_current_l3),
        requires_three_phase=True,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    coordinator: DazeCoordinator = hass.data[DOMAIN][entry.entry_id]

    entities: list[SensorEntity] = []
    for network_uid, network_data in coordinator.data.networks.items():
        network = network_data.network
        entities.append(DazeNetworkTariffSensor(coordinator, network_uid, network))

        for evse in network_data.evses:
            for description in EVSE_SENSOR_DESCRIPTIONS:
                if description.requires_three_phase and not evse.evse_is_three_phase:
                    continue
                entities.append(
                    DazeEvseSensor(coordinator, network_uid, evse.serial_number, description)
                )

            for socket in evse.sockets:
                for description in SOCKET_SENSOR_DESCRIPTIONS:
                    if description.requires_three_phase and not evse.evse_is_three_phase:
                        continue
                    entities.append(
                        DazeSocketSensor(
                            coordinator, network_uid, evse.serial_number, socket.id, description
                        )
                    )

    async_add_entities(entities)


class DazeSocketSensor(DazeSocketEntity, SensorEntity):
    entity_description: DazeSocketSensorEntityDescription

    def __init__(
        self,
        coordinator: DazeCoordinator,
        network_uid: str,
        evse_serial: str,
        socket_id: str,
        description: DazeSocketSensorEntityDescription,
    ) -> None:
        super().__init__(coordinator, network_uid, evse_serial, socket_id)
        self.entity_description = description
        self._attr_unique_id = f"{socket_id}_{description.key}"
        evse = self._evse
        socket = self._socket
        if evse is not None and socket is not None:
            self._attr_device_info = socket_device_info(evse, socket)

    @property
    def native_value(self) -> StateType | datetime:
        socket = self._socket
        return self.entity_description.value_fn(socket) if socket is not None else None


class DazeEvseSensor(DazeEvseEntity, SensorEntity):
    entity_description: DazeEvseSensorEntityDescription

    def __init__(
        self,
        coordinator: DazeCoordinator,
        network_uid: str,
        evse_serial: str,
        description: DazeEvseSensorEntityDescription,
    ) -> None:
        super().__init__(coordinator, network_uid, evse_serial)
        self.entity_description = description
        self._attr_unique_id = f"{evse_serial}_{description.key}"
        evse = self._evse
        if evse is not None:
            self._attr_device_info = evse_device_info(self._network_data.network, evse)

    @property
    def native_value(self) -> StateType:
        evse = self._evse
        return self.entity_description.value_fn(evse) if evse is not None else None


class DazeNetworkTariffSensor(DazeNetworkEntity, SensorEntity):
    _attr_translation_key = "tariff"
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(
        self, coordinator: DazeCoordinator, network_uid: str, network: DazeNetwork
    ) -> None:
        super().__init__(coordinator, network_uid)
        self._attr_unique_id = f"{network_uid}_tariff"
        self._attr_device_info = network_device_info(network)

    @property
    def native_value(self) -> StateType:
        network = self._network
        return network.price_energy if network is not None else None

    @property
    def extra_state_attributes(self) -> dict[str, StateType]:
        network = self._network
        if network is None:
            return {}
        return {
            "currency_code": network.currency.code,
            "currency_symbol": network.currency.symbol,
            "energy_cost": network.energy_cost,
        }
