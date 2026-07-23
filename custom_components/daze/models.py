"""Lightweight data models for the Daze backend.

These mirror the shape of the (undocumented, reverse-engineered) REST responses from
webapi.dazeservice.com just closely enough to serve the v1 sensor set. Unknown/unused
fields in the raw payloads are simply ignored rather than modeled - do not try to
capture every field the vendor's app happens to use internally.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class DazeCurrency:
    code: str | None
    symbol: str | None

    @classmethod
    def from_dict(cls, raw: dict | None) -> "DazeCurrency":
        raw = raw or {}
        return cls(code=raw.get("code"), symbol=raw.get("symbol"))


@dataclass
class DazeNetwork:
    """A "network" in Daze's model is one physical site/installation."""

    uid: str
    name: str | None
    address: str | None
    city: str | None
    country: str | None
    time_zone: str | None
    currency: DazeCurrency
    energy_cost: float | None
    price_energy: float | None
    is_photovoltaic: bool
    grid_is_three_phase: bool
    supply_max_power: int | None
    num_evses_in_network: int | None

    @classmethod
    def from_dict(cls, raw: dict) -> "DazeNetwork":
        return cls(
            uid=raw["uid"],
            name=raw.get("name"),
            address=raw.get("address"),
            city=raw.get("city"),
            country=raw.get("country"),
            time_zone=raw.get("timeZone"),
            currency=DazeCurrency.from_dict(raw.get("currency")),
            energy_cost=raw.get("energyCost"),
            price_energy=raw.get("priceEnergy"),
            is_photovoltaic=bool(raw.get("isPhotovoltaic", False)),
            grid_is_three_phase=bool(raw.get("gridIsThreePhase", False)),
            supply_max_power=raw.get("supplyMaxPower"),
            num_evses_in_network=raw.get("numEvsesInNetwork"),
        )


@dataclass
class DazeSocket:
    """A charging connector. An EVSE (wallbox) has one or more sockets."""

    id: str
    serial_number: str
    is_primary: bool
    last_status: int | None
    operation_mode: int | None
    last_power: int | None  # W
    last_energy: int | None  # Wh, current/last session
    last_max_charging_current: int | None  # mA
    last_charging_current_l1: int | None  # mA
    last_charging_current_l2: int | None  # mA
    last_charging_current_l3: int | None  # mA
    last_ac_voltage_l1: int | None  # V
    last_ac_voltage_l2: int | None  # V
    last_ac_voltage_l3: int | None  # V
    last_board_temperature: int | None  # degC
    last_case_temperature: int | None  # degC
    last_fan_status: int | None
    last_session_id: int | None
    last_attributes_updated_on: str | None

    # Populated separately from GET /v3/sockets/{serial}/remoteInfo.
    evse_state: int | None = None
    evse_suspension_reason: int | None = None
    evse_system_error: int | None = None
    is_paused: bool | None = None
    active: bool | None = None

    @classmethod
    def from_dict(cls, raw: dict) -> "DazeSocket":
        return cls(
            id=raw["id"],
            serial_number=raw["serialNumber"],
            is_primary=bool(raw.get("isPrimary", False)),
            last_status=raw.get("lastStatus"),
            operation_mode=raw.get("operationMode"),
            last_power=raw.get("lastPower"),
            last_energy=raw.get("lastEnergy"),
            last_max_charging_current=raw.get("lastMaxChargingCurrent"),
            last_charging_current_l1=raw.get("lastChargingCurrentInstantL1"),
            last_charging_current_l2=raw.get("lastChargingCurrentInstantL2"),
            last_charging_current_l3=raw.get("lastChargingCurrentInstantL3"),
            last_ac_voltage_l1=raw.get("lastACVoltageL1"),
            last_ac_voltage_l2=raw.get("lastACVoltageL2"),
            last_ac_voltage_l3=raw.get("lastACVoltageL3"),
            last_board_temperature=raw.get("lastBoardL1Temperature"),
            last_case_temperature=raw.get("lastCaseTemperature"),
            last_fan_status=raw.get("lastFanStatus"),
            last_session_id=raw.get("lastSessionId"),
            last_attributes_updated_on=raw.get("lastAttributesUpdatedOn"),
        )

    def apply_remote_info(self, raw: dict) -> None:
        """Merge in GET /v3/sockets/{serial}/remoteInfo data."""
        self.evse_state = raw.get("evseState")
        self.evse_suspension_reason = raw.get("evseSuspensionReason")
        self.evse_system_error = raw.get("evseSystemError")
        self.is_paused = raw.get("isPaused")
        self.active = raw.get("active")


@dataclass
class DazeEvse:
    """A wallbox. Carries firmware/connectivity info; telemetry lives on its sockets."""

    serial_number: str
    evse_name: str | None
    device_profile: str | None
    software_version: str | None
    firmware_version: str | None
    wifi_enabled: bool
    wifi_ssid: str | None
    evse_is_three_phase: bool
    active: bool
    last_supply_grid_instant_current_l1: int | None  # mA
    last_supply_grid_instant_current_l2: int | None  # mA
    last_supply_grid_instant_current_l3: int | None  # mA
    sockets: list[DazeSocket] = field(default_factory=list)

    @classmethod
    def from_dict(cls, raw: dict) -> "DazeEvse":
        return cls(
            serial_number=raw["serialNumber"],
            evse_name=raw.get("evseName"),
            device_profile=raw.get("deviceProfile"),
            software_version=raw.get("softwareVersion"),
            firmware_version=raw.get("firmwareVersion"),
            wifi_enabled=bool(raw.get("wifiEnabled", False)),
            wifi_ssid=raw.get("wifiSSID"),
            evse_is_three_phase=bool(raw.get("evseIsThreePhase", False)),
            active=bool(raw.get("active", False)),
            last_supply_grid_instant_current_l1=raw.get("lastSupplyGridInstantCurrentL1"),
            last_supply_grid_instant_current_l2=raw.get("lastSupplyGridInstantCurrentL2"),
            last_supply_grid_instant_current_l3=raw.get("lastSupplyGridInstantCurrentL3"),
            sockets=[DazeSocket.from_dict(s) for s in raw.get("sockets", [])],
        )


@dataclass
class DazeNetworkData:
    network: DazeNetwork
    evses: list[DazeEvse] = field(default_factory=list)


@dataclass
class DazeAccountData:
    """Everything fetched for one Daze account in a single coordinator refresh."""

    identity_id: str
    networks: dict[str, DazeNetworkData] = field(default_factory=dict)
