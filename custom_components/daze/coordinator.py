"""Data update coordinator for the Daze integration.

One coordinator per config entry (i.e. per Daze account) - see the plan for why this
is preferred over one coordinator per network: the full fetch tree is cheap even for
multi-network accounts, and a token failure invalidates the whole account regardless
of coordinator granularity.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import timedelta

from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import DazeApiClient, DazeCannotConnectError
from .const import DOMAIN, MAX_CONCURRENT_SOCKET_REQUESTS
from .models import DazeAccountData, DazeNetworkData

_LOGGER = logging.getLogger(__name__)


class DazeCoordinator(DataUpdateCoordinator[DazeAccountData]):
    def __init__(
        self,
        hass: HomeAssistant,
        api: DazeApiClient,
        email: str,
        identity_id: str,
        update_interval: timedelta,
    ) -> None:
        super().__init__(
            hass,
            _LOGGER,
            name=f"{DOMAIN} ({email})",
            update_interval=update_interval,
        )
        self._api = api
        self._email = email
        self._identity_id = identity_id

    @property
    def api(self) -> DazeApiClient:
        """The REST client, for platforms that send commands outside the poll cycle."""
        return self._api

    async def _async_update_data(self) -> DazeAccountData:
        try:
            networks = await self._api.async_get_networks(self._email)

            networks_data: dict[str, DazeNetworkData] = {}
            for network in networks:
                evses = await self._api.async_get_network_evses(network.uid)
                await self._async_fill_socket_remote_info(evses)
                await self._async_fill_command_authorizations(evses)
                networks_data[network.uid] = DazeNetworkData(network=network, evses=evses)

            return DazeAccountData(identity_id=self._identity_id, networks=networks_data)
        except ConfigEntryAuthFailed:
            raise
        except DazeCannotConnectError as err:
            raise UpdateFailed(str(err)) from err

    async def _async_fill_socket_remote_info(self, evses) -> None:
        semaphore = asyncio.Semaphore(MAX_CONCURRENT_SOCKET_REQUESTS)

        async def _fetch(socket) -> None:
            async with semaphore:
                remote_info = await self._api.async_get_socket_remote_info(socket.serial_number)
                if remote_info is not None:
                    socket.apply_remote_info(remote_info)

        sockets = [socket for evse in evses for socket in evse.sockets]
        if not sockets:
            return

        # return_exceptions=True so a single failing socket does not leave its siblings
        # running detached: a bare gather() propagates the first exception immediately
        # without cancelling the rest, and those orphans then surface as "Task exception
        # was never retrieved" in the log long after the update was abandoned.
        results = await asyncio.gather(
            *(_fetch(socket) for socket in sockets), return_exceptions=True
        )
        for result in results:
            if isinstance(result, BaseException):
                raise result

    async def _async_fill_command_authorizations(self, evses) -> None:
        """Merge, per EVSE, which charge command each of its sockets accepts.

        One request per EVSE, not per socket: the endpoint answers for every socket of
        the wallbox at once. Same gather/return_exceptions discipline as remoteInfo.
        """
        semaphore = asyncio.Semaphore(MAX_CONCURRENT_SOCKET_REQUESTS)

        async def _fetch(evse) -> None:
            async with semaphore:
                raw = await self._api.async_get_command_authorizations(evse.serial_number)
                if not raw:
                    return
                by_serial = {
                    entry.get("socketSerialNumber"): entry.get("availableChargeCommand")
                    for entry in raw.get("socketAvailableChargeCommand") or []
                }
                for socket in evse.sockets:
                    if socket.serial_number in by_serial:
                        socket.apply_command_authorization(by_serial[socket.serial_number])

        evses_with_sockets = [evse for evse in evses if evse.sockets]
        if not evses_with_sockets:
            return

        results = await asyncio.gather(
            *(_fetch(evse) for evse in evses_with_sockets), return_exceptions=True
        )
        for result in results:
            if isinstance(result, BaseException):
                raise result
