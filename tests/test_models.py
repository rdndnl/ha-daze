from __future__ import annotations

from custom_components.daze.models import DazeEvse, DazeNetwork


def test_network_from_dict(networks_data):
    network = DazeNetwork.from_dict(networks_data[0])
    assert network.uid == "00000000-0000-0000-0000-000000000003"
    assert network.name == "testnet"
    assert network.currency.code == "EUR"
    assert network.currency.symbol == "€"
    assert network.is_photovoltaic is False
    assert network.num_evses_in_network == 1


def test_evse_from_dict_with_nested_socket(evses_data):
    evse = DazeEvse.from_dict(evses_data[0])
    assert evse.serial_number == "TEST0000001"
    assert evse.wifi_ssid == "TestWiFi"
    assert evse.software_version == "2.7.1"
    assert len(evse.sockets) == 1

    socket = evse.sockets[0]
    assert socket.id == "00000000-0000-0000-0000-000000000007"
    assert socket.serial_number == "TEST0000001"
    assert socket.is_primary is True
    assert socket.last_power == 0
    assert socket.last_ac_voltage_l1 == 229
    assert socket.last_board_temperature == 34
    # remoteInfo fields are unset until apply_remote_info is called
    assert socket.evse_state is None


def test_socket_apply_remote_info(evses_data, remote_info_data):
    evse = DazeEvse.from_dict(evses_data[0])
    socket = evse.sockets[0]

    socket.apply_remote_info(remote_info_data)

    assert socket.evse_state == 1
    assert socket.evse_suspension_reason == 0
    assert socket.is_paused is False
    assert socket.active is True


def test_socket_apply_remote_info_without_session_clears_session_fields(
    evses_data, remote_info_data
):
    evse = DazeEvse.from_dict(evses_data[0])
    socket = evse.sockets[0]
    socket.session_id = 1  # stale value from a previous poll

    socket.apply_remote_info(remote_info_data)  # chargeSession: null

    assert socket.session_id is None
    assert socket.session_start_time is None
    assert socket.session_charge_time is None
    assert socket.session_user_name is None


def test_socket_apply_remote_info_with_charge_session(evses_data, remote_info_charging_data):
    evse = DazeEvse.from_dict(evses_data[0])
    socket = evse.sockets[0]

    socket.apply_remote_info(remote_info_charging_data)

    assert socket.evse_state == 3
    assert socket.session_id == 1784747643733
    assert socket.session_start_time == "2026-07-22T19:14:03.733Z"
    assert socket.session_charge_time == "01:05:30"
    assert socket.session_user_name == "Test User"


def test_socket_session_user_name_falls_back_to_available_half(
    evses_data, remote_info_charging_data
):
    evse = DazeEvse.from_dict(evses_data[0])
    socket = evse.sockets[0]
    remote_info_charging_data["chargeSession"]["user"] = {"userName": None, "userSurname": "Only"}

    socket.apply_remote_info(remote_info_charging_data)

    assert socket.session_user_name == "Only"


def test_socket_apply_command_authorization(evses_data):
    evse = DazeEvse.from_dict(evses_data[0])
    socket = evse.sockets[0]
    assert socket.available_charge_command is None

    socket.apply_command_authorization(2)

    assert socket.available_charge_command == 2
