from __future__ import annotations

from datetime import timedelta
from unittest.mock import AsyncMock

import pytest

from custom_components.daze.button import BUTTON_DESCRIPTIONS, DazeChargeButton
from custom_components.daze.coordinator import DazeCoordinator
from custom_components.daze.models import (
    DazeAccountData,
    DazeEvse,
    DazeNetwork,
    DazeNetworkData,
)


def _by_key(key):
    return next(d for d in BUTTON_DESCRIPTIONS if d.key == key)


@pytest.mark.parametrize(
    ("key", "api_method"),
    [
        ("start_charge", "async_start_charge"),
        ("resume_charge", "async_play_charge"),
        ("stop_charge", "async_stop_charge"),
    ],
)
async def test_press_fn_maps_to_api_command(key, api_method):
    api = AsyncMock()

    await _by_key(key).press_fn(api, "TEST0000001")

    getattr(api, api_method).assert_awaited_once_with("TEST0000001")
    for other in ("async_start_charge", "async_play_charge", "async_stop_charge"):
        if other != api_method:
            getattr(api, other).assert_not_awaited()


async def test_press_uses_socket_serial_and_refreshes(hass, networks_data, evses_data):
    network = DazeNetwork.from_dict(networks_data[0])
    evse = DazeEvse.from_dict(evses_data[0])
    socket = evse.sockets[0]
    api = AsyncMock()
    coordinator = DazeCoordinator(
        hass, api, email="a@b.com", identity_id="identity-1", update_interval=timedelta(seconds=30)
    )
    coordinator.data = DazeAccountData(
        identity_id="identity-1",
        networks={network.uid: DazeNetworkData(network=network, evses=[evse])},
    )
    coordinator.async_request_refresh = AsyncMock()

    button = DazeChargeButton(
        coordinator, network.uid, evse.serial_number, socket.id, _by_key("stop_charge")
    )
    assert button.unique_id == f"{socket.id}_stop_charge"

    await button.async_press()

    api.async_stop_charge.assert_awaited_once_with(socket.serial_number)
    coordinator.async_request_refresh.assert_awaited_once()
