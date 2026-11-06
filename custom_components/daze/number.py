"""Number platform for Daze: the wallbox's maximum charging power, in kW.

The backend stores a per-phase current in milliamps (maxExternalChargingCurrent), but
the vendor app shows and sets it as kilowatts, and that is what people think in. The
app converts with a fixed 230 V times the wallbox's phase count - observed on a
three-phase DT01: "4.5 kW" was written as 6521 mA and "11.1 kW" as 16086 mA, i.e.
floor(kW * 1e6 / (230 * 3)). This entity does the same conversion both ways, so the
value here always matches what the app displays.
"""

from __future__ import annotations

import math
import time

from homeassistant.components.number import NumberDeviceClass, NumberEntity, NumberMode
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import UnitOfPower
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN, OPTIMISTIC_STATE_TIMEOUT_SECONDS
from .coordinator import DazeCoordinator
from .entity import DazeEvseEntity, evse_device_info
from .exceptions import DazeCannotConnectError

# Fixed voltage the vendor app uses for its kW <-> A conversion (not the measured one).
NOMINAL_VOLTAGE = 230
# Lowest current the wallbox accepts: 6000 mA was rejected, 6521 mA accepted (it is
# also what the app writes for its minimum). Below ~6 A no EV charges anyway.
MIN_CURRENT_MA = 6521
# Fallback ceiling when the backend does not report the installation limit.
DEFAULT_MAX_CURRENT_MA = 32000


def current_ma_to_power_kw(current_ma: int, phases: int) -> float:
    """Per-phase milliamps -> kW as the app shows it (one decimal)."""
    return round(current_ma * NOMINAL_VOLTAGE * phases / 1_000_000, 1)


def power_kw_to_current_ma(power_kw: float, phases: int) -> int:
    """kW -> per-phase milliamps, rounded down like the app (4.5 kW -> 6521, not 6522)."""
    return math.floor(power_kw * 1_000_000 / (NOMINAL_VOLTAGE * phases))


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    coordinator: DazeCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities(
        DazeMaxPowerNumber(coordinator, network_uid, evse.serial_number)
        for network_uid, network_data in coordinator.data.networks.items()
        for evse in network_data.evses
    )


class DazeMaxPowerNumber(DazeEvseEntity, NumberEntity):
    """Maximum charging power of one wallbox, as set by the app's power slider."""

    _attr_translation_key = "max_power"
    _attr_device_class = NumberDeviceClass.POWER
    _attr_native_unit_of_measurement = UnitOfPower.KILO_WATT
    _attr_native_step = 0.1
    _attr_mode = NumberMode.SLIDER

    def __init__(self, coordinator: DazeCoordinator, network_uid: str, evse_serial: str) -> None:
        super().__init__(coordinator, network_uid, evse_serial)
        self._attr_unique_id = f"{evse_serial}_max_power"
        self._optimistic_kw: float | None = None
        self._optimistic_until: float = 0.0
        network_data = self._network_data
        evse = self._evse
        if network_data is not None and evse is not None:
            self._attr_device_info = evse_device_info(network_data.network, evse)

    # --- conversion helpers -------------------------------------------------------

    @property
    def _phases(self) -> int:
        evse = self._evse
        return 3 if evse is not None and evse.evse_is_three_phase else 1

    def _ma_to_kw(self, current_ma: int) -> float:
        return current_ma_to_power_kw(current_ma, self._phases)

    def _kw_to_ma(self, power_kw: float) -> int:
        return power_kw_to_current_ma(power_kw, self._phases)

    # --- NumberEntity -------------------------------------------------------------

    @property
    def native_min_value(self) -> float:
        return self._ma_to_kw(MIN_CURRENT_MA)

    @property
    def native_max_value(self) -> float:
        evse = self._evse
        ceiling = (evse.max_installation_current if evse else None) or DEFAULT_MAX_CURRENT_MA
        return self._ma_to_kw(ceiling)

    @property
    def native_value(self) -> float | None:
        if self._optimistic_kw is not None and time.monotonic() < self._optimistic_until:
            return self._optimistic_kw
        evse = self._evse
        if evse is None or evse.max_external_charging_current is None:
            return None
        return self._ma_to_kw(evse.max_external_charging_current)

    async def async_set_native_value(self, value: float) -> None:
        current_ma = max(MIN_CURRENT_MA, self._kw_to_ma(value))
        try:
            await self.coordinator.api.async_set_max_charging_current(self._evse_serial, current_ma)
        except DazeCannotConnectError as err:
            # e.g. error 369 (current out of range) when a grid power cap applies.
            raise HomeAssistantError(f"La colonnina ha rifiutato {value} kW: {err}") from err
        self._optimistic_kw = self._ma_to_kw(current_ma)
        self._optimistic_until = time.monotonic() + OPTIMISTIC_STATE_TIMEOUT_SECONDS
        self.async_write_ha_state()
        await self.coordinator.async_request_refresh()

    @callback
    def _handle_coordinator_update(self) -> None:
        evse = self._evse
        if (
            self._optimistic_kw is not None
            and evse is not None
            and evse.max_external_charging_current is not None
            and self._ma_to_kw(evse.max_external_charging_current) == self._optimistic_kw
        ):
            self._optimistic_kw = None
        super()._handle_coordinator_update()
