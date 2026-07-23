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

    async def _async_update_data(self) -> DazeAccountData:
        try:
            networks = await self._api.async_get_networks(self._email)

            networks_data: dict[str, DazeNetworkData] = {}
            for network in networks:
                evses = await self._api.async_get_network_evses(network.uid)
                await self._async_fill_socket_remote_info(evses)
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
        if sockets:
            await asyncio.gather(*(_fetch(socket) for socket in sockets))
