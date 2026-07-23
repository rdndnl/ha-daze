from __future__ import annotations

from custom_components.daze.models import DazeEvse
from custom_components.daze.sensor import (
    EVSE_SENSOR_DESCRIPTIONS,
    SOCKET_SENSOR_DESCRIPTIONS,
)


def _by_key(descriptions, key):
    return next(d for d in descriptions if d.key == key)


def test_power_value_fn_passthrough(evses_data):
    evse = DazeEvse.from_dict(evses_data[0])
    socket = evse.sockets[0]
    socket.last_power = 7360
    assert _by_key(SOCKET_SENSOR_DESCRIPTIONS, "power").value_fn(socket) == 7360


def test_session_energy_converts_wh_to_kwh(evses_data):
    evse = DazeEvse.from_dict(evses_data[0])
    socket = evse.sockets[0]
    socket.last_energy = 35670
    assert _by_key(SOCKET_SENSOR_DESCRIPTIONS, "session_energy").value_fn(socket) == 35.67


def test_session_energy_none_stays_none(evses_data):
    evse = DazeEvse.from_dict(evses_data[0])
    socket = evse.sockets[0]
    socket.last_energy = None
    assert _by_key(SOCKET_SENSOR_DESCRIPTIONS, "session_energy").value_fn(socket) is None


def test_charging_current_converts_ma_to_a(evses_data):
    evse = DazeEvse.from_dict(evses_data[0])
    socket = evse.sockets[0]
    socket.last_charging_current_l1 = 16000
    assert _by_key(SOCKET_SENSOR_DESCRIPTIONS, "charging_current_l1").value_fn(socket) == 16.0


def test_voltage_passthrough_no_conversion(evses_data):
    evse = DazeEvse.from_dict(evses_data[0])
    socket = evse.sockets[0]
    assert _by_key(SOCKET_SENSOR_DESCRIPTIONS, "voltage_l1").value_fn(socket) == 229


def test_raw_status_enums_exposed_unmapped(evses_data, remote_info_data):
    evse = DazeEvse.from_dict(evses_data[0])
    socket = evse.sockets[0]
    socket.apply_remote_info(remote_info_data)
    assert _by_key(SOCKET_SENSOR_DESCRIPTIONS, "status").value_fn(socket) == socket.last_status
    assert _by_key(SOCKET_SENSOR_DESCRIPTIONS, "evse_state").value_fn(socket) == 1


def test_l2_l3_descriptions_flagged_for_three_phase_gating():
    for key in ("charging_current_l2", "charging_current_l3", "voltage_l2", "voltage_l3"):
        assert _by_key(SOCKET_SENSOR_DESCRIPTIONS, key).requires_three_phase is True
    assert _by_key(SOCKET_SENSOR_DESCRIPTIONS, "charging_current_l1").requires_three_phase is False


def test_grid_current_gated_on_three_phase_too():
    assert _by_key(EVSE_SENSOR_DESCRIPTIONS, "grid_current_l2").requires_three_phase is True
    assert _by_key(EVSE_SENSOR_DESCRIPTIONS, "grid_current_l1").requires_three_phase is False


def test_evse_diagnostic_value_fns(evses_data):
    evse = DazeEvse.from_dict(evses_data[0])
    assert _by_key(EVSE_SENSOR_DESCRIPTIONS, "wifi_ssid").value_fn(evse) == "honeypot"
    assert _by_key(EVSE_SENSOR_DESCRIPTIONS, "software_version").value_fn(evse) == "2.7.1"
    assert _by_key(EVSE_SENSOR_DESCRIPTIONS, "grid_current_l1").value_fn(evse) == 1.616
