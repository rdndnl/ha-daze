from __future__ import annotations

from datetime import timedelta
from unittest.mock import AsyncMock, patch

import pytest

from custom_components.daze.const import (
    CHARGE_COMMAND_PLAY,
    CHARGE_COMMAND_STOP,
    OPTIMISTIC_STATE_TIMEOUT_SECONDS,
)
from custom_components.daze.coordinator import DazeCoordinator
from custom_components.daze.models import (
    DazeAccountData,
    DazeEvse,
    DazeNetwork,
    DazeNetworkData,
)
from custom_components.daze.switch import DazeChargingSwitch


@pytest.fixture
def api() -> AsyncMock:
    return AsyncMock()


@pytest.fixture
def switch(hass, api, networks_data, evses_data) -> DazeChargingSwitch:
    """A switch bound to a coordinator that already holds one network/EVSE/socket.

    No config entry, no entity platform: the entity is exercised directly, with the
    two Home Assistant touch points it uses (state write, refresh request) stubbed.
    """
    network = DazeNetwork.from_dict(networks_data[0])
    evse = DazeEvse.from_dict(evses_data[0])
    coordinator = DazeCoordinator(
        hass, api, email="a@b.com", identity_id="identity-1", update_interval=timedelta(seconds=30)
    )
    coordinator.data = DazeAccountData(
        identity_id="identity-1",
        networks={network.uid: DazeNetworkData(network=network, evses=[evse])},
    )
    coordinator.async_request_refresh = AsyncMock()

    entity = DazeChargingSwitch(coordinator, network.uid, evse.serial_number, evse.sockets[0].id)
    entity.hass = hass
    with patch.object(DazeChargingSwitch, "async_write_ha_state"):
        yield entity


def _socket(switch: DazeChargingSwitch):
    return switch.coordinator.data.networks[switch._network_uid].evses[0].sockets[0]


def test_is_on_follows_available_charge_command(switch):
    socket = _socket(switch)

    socket.apply_command_authorization(CHARGE_COMMAND_STOP)
    assert switch.is_on is True

    socket.apply_command_authorization(CHARGE_COMMAND_PLAY)
    assert switch.is_on is False


def test_is_on_is_off_not_unknown_when_no_command_offered(switch):
    """Idle wallbox offers neither command; the switch must stay pressable (off)."""
    socket = _socket(switch)
    socket.apply_command_authorization(None)
    assert switch.is_on is False
    socket.apply_command_authorization(0)
    assert switch.is_on is False


async def test_turn_on_idle_starts_new_session(switch, api):
    socket = _socket(switch)
    socket.apply_command_authorization(None)
    socket.is_paused = False

    await switch.async_turn_on()

    api.async_start_charge.assert_awaited_once_with(socket.serial_number)
    api.async_play_charge.assert_not_awaited()
    switch.coordinator.async_request_refresh.assert_awaited_once()


async def test_turn_on_paused_resumes_with_playcharge(switch, api):
    socket = _socket(switch)
    socket.apply_command_authorization(CHARGE_COMMAND_PLAY)

    await switch.async_turn_on()

    api.async_play_charge.assert_awaited_once_with(socket.serial_number)
    api.async_start_charge.assert_not_awaited()


async def test_turn_on_honours_is_paused_flag(switch, api):
    """remoteInfo's isPaused alone is enough to pick playcharge over startcharge."""
    socket = _socket(switch)
    socket.apply_command_authorization(None)
    socket.is_paused = True

    await switch.async_turn_on()

    api.async_play_charge.assert_awaited_once_with(socket.serial_number)
    api.async_start_charge.assert_not_awaited()


async def test_turn_off_sends_stopcharge(switch, api):
    socket = _socket(switch)
    socket.apply_command_authorization(CHARGE_COMMAND_STOP)

    await switch.async_turn_off()

    api.async_stop_charge.assert_awaited_once_with(socket.serial_number)
    switch.coordinator.async_request_refresh.assert_awaited_once()


async def test_optimistic_state_bridges_backend_lag(switch):
    socket = _socket(switch)
    socket.apply_command_authorization(CHARGE_COMMAND_PLAY)
    assert switch.is_on is False

    await switch.async_turn_on()
    assert switch.is_on is True

    # A poll that still reports the old value must not flip the switch back.
    switch._handle_coordinator_update()
    assert switch.is_on is True

    # Once the backend agrees, the assumption is dropped...
    socket.apply_command_authorization(CHARGE_COMMAND_STOP)
    switch._handle_coordinator_update()
    assert switch.is_on is True

    # ...so a later genuine change from the wallbox side shows through immediately.
    socket.apply_command_authorization(CHARGE_COMMAND_PLAY)
    switch._handle_coordinator_update()
    assert switch.is_on is False


async def test_optimistic_state_expires(switch):
    """A command the wallbox silently ignored must correct itself after the timeout."""
    socket = _socket(switch)
    socket.apply_command_authorization(CHARGE_COMMAND_PLAY)

    with patch("custom_components.daze.switch.time.monotonic", return_value=1000.0):
        await switch.async_turn_on()
        assert switch.is_on is True

    with patch(
        "custom_components.daze.switch.time.monotonic",
        return_value=1000.0 + OPTIMISTIC_STATE_TIMEOUT_SECONDS,
    ):
        assert switch.is_on is False


async def test_commands_are_noops_without_socket(switch, api):
    switch.coordinator.data = DazeAccountData(identity_id="identity-1", networks={})

    await switch.async_turn_on()
    await switch.async_turn_off()

    api.async_start_charge.assert_not_awaited()
    api.async_play_charge.assert_not_awaited()
    api.async_stop_charge.assert_not_awaited()
    assert switch.available is False
