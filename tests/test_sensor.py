from __future__ import annotations

from datetime import UTC, datetime

import pytest

from custom_components.daze.models import DazeEvse
from custom_components.daze.sensor import (
    EVSE_SENSOR_DESCRIPTIONS,
    SOCKET_SENSOR_DESCRIPTIONS,
    _charge_time_to_minutes,
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


def test_status_and_evse_state_mapped_to_labels(evses_data, remote_info_data):
    evse = DazeEvse.from_dict(evses_data[0])
    socket = evse.sockets[0]
    socket.apply_remote_info(remote_info_data)
    assert _by_key(SOCKET_SENSOR_DESCRIPTIONS, "status").value_fn(socket) == "standby"
    assert _by_key(SOCKET_SENSOR_DESCRIPTIONS, "evse_state").value_fn(socket) == "standby"


def test_status_unknown_value_maps_to_none(evses_data):
    evse = DazeEvse.from_dict(evses_data[0])
    socket = evse.sockets[0]
    socket.last_status = 999  # not a known EVSE state code
    assert _by_key(SOCKET_SENSOR_DESCRIPTIONS, "status").value_fn(socket) is None


def test_system_error_mapped_to_label(evses_data, remote_info_data):
    evse = DazeEvse.from_dict(evses_data[0])
    socket = evse.sockets[0]
    socket.apply_remote_info(remote_info_data)
    assert _by_key(SOCKET_SENSOR_DESCRIPTIONS, "system_error").value_fn(socket) == "none"


def test_l2_l3_descriptions_flagged_for_three_phase_gating():
    for key in ("charging_current_l2", "charging_current_l3", "voltage_l2", "voltage_l3"):
        assert _by_key(SOCKET_SENSOR_DESCRIPTIONS, key).requires_three_phase is True
    assert _by_key(SOCKET_SENSOR_DESCRIPTIONS, "charging_current_l1").requires_three_phase is False


def test_grid_current_gated_on_three_phase_too():
    assert _by_key(EVSE_SENSOR_DESCRIPTIONS, "grid_current_l2").requires_three_phase is True
    assert _by_key(EVSE_SENSOR_DESCRIPTIONS, "grid_current_l1").requires_three_phase is False


def test_evse_diagnostic_value_fns(evses_data):
    evse = DazeEvse.from_dict(evses_data[0])
    assert _by_key(EVSE_SENSOR_DESCRIPTIONS, "wifi_ssid").value_fn(evse) == "TestWiFi"
    assert _by_key(EVSE_SENSOR_DESCRIPTIONS, "software_version").value_fn(evse) == "2.7.1"
    assert _by_key(EVSE_SENSOR_DESCRIPTIONS, "grid_current_l1").value_fn(evse) == 1.616


def test_available_charge_command_mapped_to_label(evses_data):
    evse = DazeEvse.from_dict(evses_data[0])
    socket = evse.sockets[0]
    description = _by_key(SOCKET_SENSOR_DESCRIPTIONS, "available_charge_command")

    socket.apply_command_authorization(2)
    assert description.value_fn(socket) == "stop"
    socket.apply_command_authorization(3)
    assert description.value_fn(socket) == "play"
    # Neither command offered (idle / no cable): not a known option, so unknown.
    socket.apply_command_authorization(0)
    assert description.value_fn(socket) is None
    socket.apply_command_authorization(None)
    assert description.value_fn(socket) is None


def test_session_sensors_from_charge_session(evses_data, remote_info_charging_data):
    evse = DazeEvse.from_dict(evses_data[0])
    socket = evse.sockets[0]
    socket.apply_remote_info(remote_info_charging_data)

    assert _by_key(SOCKET_SENSOR_DESCRIPTIONS, "session_id").value_fn(socket) == 1784747643733
    assert _by_key(SOCKET_SENSOR_DESCRIPTIONS, "session_start").value_fn(socket) == datetime(
        2026, 7, 22, 19, 14, 3, 733000, tzinfo=UTC
    )
    assert _by_key(SOCKET_SENSOR_DESCRIPTIONS, "session_duration").value_fn(socket) == 65.5
    assert _by_key(SOCKET_SENSOR_DESCRIPTIONS, "session_user").value_fn(socket) == "Test User"


def test_session_sensors_none_without_session(evses_data, remote_info_data):
    evse = DazeEvse.from_dict(evses_data[0])
    socket = evse.sockets[0]
    socket.apply_remote_info(remote_info_data)  # chargeSession: null

    for key in ("session_id", "session_start", "session_duration", "session_user"):
        assert _by_key(SOCKET_SENSOR_DESCRIPTIONS, key).value_fn(socket) is None


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("00:00:00", 0.0),
        ("00:30:00", 30.0),
        ("01:05:30", 65.5),
        ("26:00:00", 1560.0),  # hours are not wrapped at 24
        ("", None),
        (None, None),
        ("1:05", None),
        ("aa:bb:cc", None),
    ],
)
def test_charge_time_to_minutes(raw, expected):
    assert _charge_time_to_minutes(raw) == expected
