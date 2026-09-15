"""Button platform for Daze: explicit start / resume / stop for one socket.

These sit alongside switch.py on purpose. The switch is the thing to point automations
at; the buttons are for forcing one specific command rather than "make it charge" -
most importantly startcharge, which opens a NEW session and arms the ~60s window during
which the cable has to be plugged in.

Commands are fire-and-forget: the backend answers 200 with an empty body, so a press
requests a coordinator refresh and lets the status sensors report what happened.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from homeassistant.components.button import ButtonEntity, ButtonEntityDescription
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .api import DazeApiClient
from .const import DOMAIN
from .coordinator import DazeCoordinator
from .entity import DazeSocketEntity, socket_device_info


@dataclass(frozen=True, kw_only=True)
class DazeButtonEntityDescription(ButtonEntityDescription):
    press_fn: Callable[[DazeApiClient, str], Awaitable[None]]


BUTTON_DESCRIPTIONS: tuple[DazeButtonEntityDescription, ...] = (
    DazeButtonEntityDescription(
        key="start_charge",
        translation_key="start_charge",
        press_fn=lambda api, serial: api.async_start_charge(serial),
    ),
    DazeButtonEntityDescription(
        key="resume_charge",
        translation_key="resume_charge",
        press_fn=lambda api, serial: api.async_play_charge(serial),
    ),
    DazeButtonEntityDescription(
        key="stop_charge",
        translation_key="stop_charge",
        press_fn=lambda api, serial: api.async_stop_charge(serial),
    ),
)


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    coordinator: DazeCoordinator = hass.data[DOMAIN][entry.entry_id]

    entities: list[ButtonEntity] = []
    for network_uid, network_data in coordinator.data.networks.items():
        for evse in network_data.evses:
            for socket in evse.sockets:
                for description in BUTTON_DESCRIPTIONS:
                    entities.append(
                        DazeChargeButton(
                            coordinator, network_uid, evse.serial_number, socket.id, description
                        )
                    )

    async_add_entities(entities)


class DazeChargeButton(DazeSocketEntity, ButtonEntity):
    """Sends one specific charge command to a single socket."""

    entity_description: DazeButtonEntityDescription

    def __init__(
        self,
        coordinator: DazeCoordinator,
        network_uid: str,
        evse_serial: str,
        socket_id: str,
        description: DazeButtonEntityDescription,
    ) -> None:
        super().__init__(coordinator, network_uid, evse_serial, socket_id)
        self.entity_description = description
        self._attr_unique_id = f"{socket_id}_{description.key}"
        evse = self._evse
        socket = self._socket
        if evse is not None and socket is not None:
            self._attr_device_info = socket_device_info(evse, socket)

    async def async_press(self) -> None:
        socket = self._socket
        if socket is None:
            return
        await self.entity_description.press_fn(self.coordinator.api, socket.serial_number)
        await self.coordinator.async_request_refresh()
