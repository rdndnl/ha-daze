"""Switch platform for Daze: one charging switch per socket.

Why a switch and not just the buttons: the socket has exactly two meaningful states
here (delivering power / not delivering power), so a toggle maps onto it directly and
gives automations something to target with `switch.turn_on`.

Two things make this less trivial than it looks, and both are handled below:

1. Resuming is NOT startcharge. After a stopcharge the session stays open and only
   playcharge picks it back up; startcharge is silently ignored in that state.
2. The backend lags. A command is accepted immediately (HTTP 200, empty body) but the
   polled state keeps reporting the old value for ~10-16 seconds. Without local
   optimism the toggle springs back under the user's finger and looks broken.
"""

from __future__ import annotations

import time
from typing import Any

from homeassistant.components.switch import SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import (
    CHARGE_COMMAND_PLAY,
    CHARGE_COMMAND_STOP,
    DOMAIN,
    OPTIMISTIC_STATE_TIMEOUT_SECONDS,
)
from .coordinator import DazeCoordinator
from .entity import DazeSocketEntity, socket_device_info


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    coordinator: DazeCoordinator = hass.data[DOMAIN][entry.entry_id]

    entities: list[SwitchEntity] = []
    for network_uid, network_data in coordinator.data.networks.items():
        for evse in network_data.evses:
            for socket in evse.sockets:
                entities.append(
                    DazeChargingSwitch(coordinator, network_uid, evse.serial_number, socket.id)
                )

    async_add_entities(entities)


class DazeChargingSwitch(DazeSocketEntity, SwitchEntity):
    """Charging on/off for one socket."""

    _attr_translation_key = "charging"

    def __init__(
        self,
        coordinator: DazeCoordinator,
        network_uid: str,
        evse_serial: str,
        socket_id: str,
    ) -> None:
        super().__init__(coordinator, network_uid, evse_serial, socket_id)
        self._attr_unique_id = f"{socket_id}_charging"
        self._optimistic_is_on: bool | None = None
        self._optimistic_until: float = 0.0
        evse = self._evse
        socket = self._socket
        if evse is not None and socket is not None:
            self._attr_device_info = socket_device_info(evse, socket)

    @property
    def _reported_is_on(self) -> bool | None:
        """True/False from the backend, or None when it offers neither command."""
        socket = self._socket
        if socket is None:
            return None
        # The field names the command that is *offered*, so "stop is offered" means
        # power is flowing right now.
        if socket.available_charge_command == CHARGE_COMMAND_STOP:
            return True
        if socket.available_charge_command == CHARGE_COMMAND_PLAY:
            return False
        return None

    @property
    def is_on(self) -> bool:
        if self._optimistic_is_on is not None and time.monotonic() < self._optimistic_until:
            return self._optimistic_is_on
        # Unknown is reported as OFF rather than None on purpose. With nothing plugged
        # in the wallbox offers neither command, and greying the switch out in that
        # state broke the one workflow that matters: press start FIRST, then plug the
        # cable in within the ~60s authorization window. It must stay pressable.
        return self._reported_is_on is True

    async def async_turn_on(self, **kwargs: Any) -> None:
        socket = self._socket
        if socket is None:
            return
        # A stopped session is paused, not finished: it resumes with playcharge.
        # startcharge opens a fresh session and arms the authorization window, so it
        # is the right command when the wallbox is idle and offers nothing.
        if socket.is_paused or socket.available_charge_command == CHARGE_COMMAND_PLAY:
            await self.coordinator.api.async_play_charge(socket.serial_number)
        else:
            await self.coordinator.api.async_start_charge(socket.serial_number)
        await self._async_assume_state(True)

    async def async_turn_off(self, **kwargs: Any) -> None:
        socket = self._socket
        if socket is None:
            return
        await self.coordinator.api.async_stop_charge(socket.serial_number)
        await self._async_assume_state(False)

    async def _async_assume_state(self, is_on: bool) -> None:
        self._optimistic_is_on = is_on
        self._optimistic_until = time.monotonic() + OPTIMISTIC_STATE_TIMEOUT_SECONDS
        self.async_write_ha_state()
        # Nudge the coordinator so the real value arrives sooner than the next
        # scheduled poll; the assumed value covers the gap either way.
        await self.coordinator.async_request_refresh()

    @callback
    def _handle_coordinator_update(self) -> None:
        # Drop the assumption as soon as reality agrees with it, so a later genuine
        # change from the wallbox side is not masked by a stale override.
        if self._optimistic_is_on is not None and self._reported_is_on == self._optimistic_is_on:
            self._optimistic_is_on = None
        super()._handle_coordinator_update()
