from __future__ import annotations

import asyncio
import dataclasses
from datetime import timedelta
from unittest.mock import AsyncMock

import pytest
from homeassistant.helpers.update_coordinator import UpdateFailed

from custom_components.daze.coordinator import DazeCoordinator
from custom_components.daze.exceptions import DazeCannotConnectError
from custom_components.daze.models import DazeEvse, DazeNetwork


@pytest.mark.asyncio
async def test_coordinator_builds_account_data(
    hass, networks_data, evses_data, remote_info_data, command_authorizations_data
):
    network = DazeNetwork.from_dict(networks_data[0])
    evse = DazeEvse.from_dict(evses_data[0])

    api = AsyncMock()
    api.async_get_networks.return_value = [network]
    api.async_get_network_evses.return_value = [evse]
    api.async_get_socket_remote_info.return_value = remote_info_data
    api.async_get_command_authorizations.return_value = command_authorizations_data

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

    # commandAuthorizations was fetched once per EVSE and merged into the socket
    assert evse.sockets[0].available_charge_command == 3
    api.async_get_command_authorizations.assert_called_once_with(evse.serial_number)


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
    api.async_get_command_authorizations.assert_not_called()


@pytest.mark.asyncio
async def test_remote_info_failure_becomes_update_failed(hass, networks_data, evses_data):
    """A timeout normalised by api.py must surface as UpdateFailed, not escape raw.

    The whole poll cycle fails on purpose: data is rebuilt from scratch every refresh,
    so applying the sockets that did answer would show `unknown` telemetry for the ones
    that did not. `unavailable` entities keeping their last known value is the honest
    outcome.
    """
    network = DazeNetwork.from_dict(networks_data[0])
    evse = DazeEvse.from_dict(evses_data[0])

    api = AsyncMock()
    api.async_get_networks.return_value = [network]
    api.async_get_network_evses.return_value = [evse]
    api.async_get_socket_remote_info.side_effect = DazeCannotConnectError(
        "GET /v3/sockets/X/remoteInfo timed out after 15s"
    )

    coordinator = DazeCoordinator(
        hass, api, email="a@b.com", identity_id="identity-1", update_interval=timedelta(seconds=30)
    )

    with pytest.raises(UpdateFailed, match="timed out"):
        await coordinator._async_update_data()


@pytest.mark.asyncio
async def test_one_failing_socket_does_not_orphan_its_siblings(hass, networks_data, evses_data):
    """gather(return_exceptions=True) must wait for every socket before re-raising.

    A bare gather() propagates the first exception without cancelling the rest, leaving
    those requests running detached; their results are discarded and any exception they
    raise resurfaces much later as "Task exception was never retrieved".
    """
    network = DazeNetwork.from_dict(networks_data[0])
    evse = DazeEvse.from_dict(evses_data[0])
    slow_socket = dataclasses.replace(evse.sockets[0], serial_number="SLOW0000001")
    evse.sockets.append(slow_socket)

    finished: list[str] = []

    async def _remote_info(serial_number: str):
        if serial_number == slow_socket.serial_number:
            # Long enough that a gather() abandoning its siblings on the first failure
            # would return before this ever appends - a bare `sleep(0)` finishes within
            # the same tick and the test would pass either way.
            await asyncio.sleep(0.05)
            finished.append(serial_number)
            return {}
        raise DazeCannotConnectError("timed out")

    api = AsyncMock()
    api.async_get_networks.return_value = [network]
    api.async_get_network_evses.return_value = [evse]
    api.async_get_socket_remote_info.side_effect = _remote_info

    coordinator = DazeCoordinator(
        hass, api, email="a@b.com", identity_id="identity-1", update_interval=timedelta(seconds=30)
    )

    with pytest.raises(UpdateFailed):
        await coordinator._async_update_data()

    assert finished == [slow_socket.serial_number]


@pytest.mark.asyncio
async def test_command_authorizations_matched_by_socket_serial(
    hass, networks_data, evses_data, remote_info_data
):
    """The per-EVSE response lists every socket; each one must get its own value."""
    network = DazeNetwork.from_dict(networks_data[0])
    evse = DazeEvse.from_dict(evses_data[0])
    second_socket = dataclasses.replace(evse.sockets[0], id="socket-2", serial_number="TEST0000002")
    evse.sockets.append(second_socket)

    api = AsyncMock()
    api.async_get_networks.return_value = [network]
    api.async_get_network_evses.return_value = [evse]
    api.async_get_socket_remote_info.return_value = remote_info_data
    api.async_get_command_authorizations.return_value = {
        "evseSerialNumber": evse.serial_number,
        "socketAvailableChargeCommand": [
            {"socketSerialNumber": "TEST0000001", "availableChargeCommand": 2},
            {"socketSerialNumber": "TEST0000002", "availableChargeCommand": 3},
        ],
    }

    coordinator = DazeCoordinator(
        hass, api, email="a@b.com", identity_id="identity-1", update_interval=timedelta(seconds=30)
    )

    await coordinator._async_update_data()

    assert evse.sockets[0].available_charge_command == 2
    assert evse.sockets[1].available_charge_command == 3
    api.async_get_command_authorizations.assert_called_once_with(evse.serial_number)


@pytest.mark.asyncio
async def test_missing_command_authorizations_leave_socket_untouched(
    hass, networks_data, evses_data, remote_info_data
):
    """A 404 (api returns None) must not fail the poll - the sensors just stay unknown."""
    network = DazeNetwork.from_dict(networks_data[0])
    evse = DazeEvse.from_dict(evses_data[0])

    api = AsyncMock()
    api.async_get_networks.return_value = [network]
    api.async_get_network_evses.return_value = [evse]
    api.async_get_socket_remote_info.return_value = remote_info_data
    api.async_get_command_authorizations.return_value = None

    coordinator = DazeCoordinator(
        hass, api, email="a@b.com", identity_id="identity-1", update_interval=timedelta(seconds=30)
    )

    data = await coordinator._async_update_data()

    assert network.uid in data.networks
    assert evse.sockets[0].available_charge_command is None


@pytest.mark.asyncio
async def test_command_authorizations_failure_becomes_update_failed(
    hass, networks_data, evses_data, remote_info_data
):
    network = DazeNetwork.from_dict(networks_data[0])
    evse = DazeEvse.from_dict(evses_data[0])

    api = AsyncMock()
    api.async_get_networks.return_value = [network]
    api.async_get_network_evses.return_value = [evse]
    api.async_get_socket_remote_info.return_value = remote_info_data
    api.async_get_command_authorizations.side_effect = DazeCannotConnectError(
        "GET /v3/evses/X/commandAuthorizations timed out after 15s"
    )

    coordinator = DazeCoordinator(
        hass, api, email="a@b.com", identity_id="identity-1", update_interval=timedelta(seconds=30)
    )

    with pytest.raises(UpdateFailed, match="timed out"):
        await coordinator._async_update_data()
