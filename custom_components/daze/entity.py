"""Common entity base classes: DeviceInfo plumbing for network/EVSE/socket devices."""

from __future__ import annotations

from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import DazeCoordinator
from .models import DazeEvse, DazeNetwork, DazeNetworkData, DazeSocket


def network_device_info(network: DazeNetwork) -> DeviceInfo:
    return DeviceInfo(
        identifiers={(DOMAIN, network.uid)},
        name=network.name or network.uid,
        manufacturer="Daze",
        model="Network",
    )


def evse_device_info(network: DazeNetwork, evse: DazeEvse) -> DeviceInfo:
    return DeviceInfo(
        identifiers={(DOMAIN, evse.serial_number)},
        name=evse.evse_name or evse.serial_number,
        manufacturer="Daze",
        model=evse.device_profile,
        sw_version=evse.software_version,
        hw_version=evse.firmware_version,
        serial_number=evse.serial_number,
        via_device=(DOMAIN, network.uid),
    )


def socket_device_info(evse: DazeEvse, socket: DazeSocket) -> DeviceInfo:
    return DeviceInfo(
        identifiers={(DOMAIN, socket.id)},
        name=f"{evse.evse_name or evse.serial_number} - {socket.serial_number}",
        manufacturer="Daze",
        model="Socket",
        via_device=(DOMAIN, evse.serial_number),
    )


class DazeEntity(CoordinatorEntity[DazeCoordinator]):
    """Base for all Daze entities. Subclasses resolve their live data via network_uid."""

    _attr_has_entity_name = True

    def __init__(self, coordinator: DazeCoordinator, network_uid: str) -> None:
        super().__init__(coordinator)
        self._network_uid = network_uid

    @property
    def _network_data(self) -> DazeNetworkData | None:
        return self.coordinator.data.networks.get(self._network_uid)


class DazeNetworkEntity(DazeEntity):
    @property
    def _network(self) -> DazeNetwork | None:
        data = self._network_data
        return data.network if data else None

    @property
    def available(self) -> bool:
        return super().available and self._network is not None


class DazeEvseEntity(DazeEntity):
    def __init__(self, coordinator: DazeCoordinator, network_uid: str, evse_serial: str) -> None:
        super().__init__(coordinator, network_uid)
        self._evse_serial = evse_serial

    @property
    def _evse(self) -> DazeEvse | None:
        data = self._network_data
        if data is None:
            return None
        return next((e for e in data.evses if e.serial_number == self._evse_serial), None)

    @property
    def available(self) -> bool:
        return super().available and self._evse is not None


class DazeSocketEntity(DazeEvseEntity):
    def __init__(
        self,
        coordinator: DazeCoordinator,
        network_uid: str,
        evse_serial: str,
        socket_id: str,
    ) -> None:
        super().__init__(coordinator, network_uid, evse_serial)
        self._socket_id = socket_id

    @property
    def _socket(self) -> DazeSocket | None:
        evse = self._evse
        if evse is None:
            return None
        return next((s for s in evse.sockets if s.id == self._socket_id), None)

    @property
    def available(self) -> bool:
        return super().available and self._socket is not None
