from __future__ import annotations

from datetime import timedelta
from unittest.mock import AsyncMock

import pytest

from custom_components.daze.coordinator import DazeCoordinator
from custom_components.daze.models import DazeEvse, DazeNetwork


@pytest.mark.asyncio
async def test_coordinator_builds_account_data(hass, networks_data, evses_data, remote_info_data):
    network = DazeNetwork.from_dict(networks_data[0])
    evse = DazeEvse.from_dict(evses_data[0])

    api = AsyncMock()
    api.async_get_networks.return_value = [network]
    api.async_get_network_evses.return_value = [evse]
    api.async_get_socket_remote_info.return_value = remote_info_data

    coordinator = DazeCoordinator(
        hass,
        api,
        email="a@b.com",
        identity_id="identity-1",
        update_interval=timedelta(seconds=30),
    )

    data = await coordinator._async_update_data()

    assert data.identity_id == "identity-1"
    assert network.uid in data.networks
    network_data = data.networks[network.uid]
    assert network_data.network is network
    assert network_data.evses == [evse]

    # remoteInfo was fetched and merged into the socket
    assert evse.sockets[0].evse_state == 1
    api.async_get_socket_remote_info.assert_called_once_with(evse.sockets[0].serial_number)


@pytest.mark.asyncio
async def test_coordinator_skips_remote_info_fetch_when_no_sockets(hass, networks_data):
    network = DazeNetwork.from_dict(networks_data[0])
    evse_without_sockets = DazeEvse(
        serial_number="X",
        evse_name="x",
        device_profile=None,
        software_version=None,
        firmware_version=None,
        wifi_enabled=False,
        wifi_ssid=None,
        evse_is_three_phase=False,
        active=True,
        last_supply_grid_instant_current_l1=None,
        last_supply_grid_instant_current_l2=None,
        last_supply_grid_instant_current_l3=None,
        sockets=[],
    )

    api = AsyncMock()
    api.async_get_networks.return_value = [network]
    api.async_get_network_evses.return_value = [evse_without_sockets]

    coordinator = DazeCoordinator(
        hass, api, email="a@b.com", identity_id="identity-1", update_interval=timedelta(seconds=30)
    )

    await coordinator._async_update_data()

    api.async_get_socket_remote_info.assert_not_called()
