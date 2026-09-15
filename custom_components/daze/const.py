"""Constants for the Daze wallbox integration."""

from __future__ import annotations

from datetime import timedelta

import aiohttp

DOMAIN = "daze"

# --- Cognito / OAuth ---
# TODO: find more generic region/user pool ID
COGNITO_REGION = "eu-central-1"
COGNITO_USER_POOL_ID = "eu-central-1_vXrLKLO3t"
COGNITO_CLIENT_ID = "4m0rp7oqarbrc3hn67ivvonba8"

# --- REST backend ---
WEBAPI_BASE_URL = "https://webapi.dazeservice.com"

# Timeout applied to every outbound call, REST and Cognito alike. `connect` is
# deliberately lower than `total`: the failure mode actually observed in the wild is a
# TCP/TLS connect that hangs (aiohttp gives up inside `create_connection`, never having
# sent a byte), so there is no point spending the whole budget on a socket that is not
# coming up - leave some of it for a request that did reach the server.
REQUEST_TIMEOUT = aiohttp.ClientTimeout(total=15, connect=10)

# Immediate in-request retries after a timeout. Kept at 1 on purpose: the coordinator
# already retries the whole fetch tree every scan interval, and each retry adds up to
# another `REQUEST_TIMEOUT.total` to the worst-case duration of a poll cycle.
REQUEST_TIMEOUT_RETRIES = 1

# --- Config entry data/options keys ---
# CONF_EMAIL/CONF_PASSWORD are homeassistant.const's, reused as-is (not redefined here).
CONF_TOKEN = "token"

DEFAULT_SCAN_INTERVAL = timedelta(seconds=60)
MIN_SCAN_INTERVAL = timedelta(seconds=30)
MAX_SCAN_INTERVAL = timedelta(seconds=300)
CONF_SCAN_INTERVAL = "scan_interval"

# Number of concurrent /remoteInfo requests fired per poll cycle.
MAX_CONCURRENT_SOCKET_REQUESTS = 5

# Cognito access tokens are short-lived (observed: 3600s). Refresh proactively
# this many seconds before expiry rather than waiting for a 401.
TOKEN_REFRESH_LEEWAY_SECONDS = 300

# --- Vendor status enums ---
# `lastStatus` (from /evses) and `evseState` (from /sockets/{serial}/remoteInfo) are the
# same underlying EVSE state enum. Keys are the integer values observed on the wire;
# values are translation-key-safe identifiers, with the actual display text living
# in strings.json / translations/*.json.
EVSE_STATE_LABELS: dict[int, str] = {
    0: "unknown",
    1: "standby",
    2: "ev_connected_wait_auth",
    3: "charging",
    4: "evse_error",
    5: "ev_connected_authorized",
    6: "ev_connected_wait_power",
    7: "preparing",
    8: "unavailable",
    9: "finishing",
    10: "reserved",
    100: "scheduled_pause",
    101: "smart_tariff_pause",
}

# `evseSystemError` / `lastEVSESystemError`.
EVSE_SYSTEM_ERROR_LABELS: dict[int, str] = {
    0: "none",
    1: "fault_rcm",
    2: "fault_rcm_test",
    3: "cp_state_e",
    4: "fault_contactor",
    5: "cp_state_invalid",
    6: "overtemperature",
    7: "overcurrent",
    8: "fault_pivot",
    9: "triggered_rcbo",
    10: "evse_not_powered",
    11: "board_l1_overtemp",
}

# `availableChargeCommand` from GET /v3/evses/{serial}/commandAuthorizations. This is
# the field the vendor portal drives its own play/stop button from, and the only
# reliable signal for which command a socket will currently accept: after a stopcharge
# it flips within ~10s, while `evseState` can lag noticeably longer (16s observed) and
# its value 6 ("ev_connected_wait_power") is not a pause marker. Anything other than
# the two values below means neither command is offered (idle, no cable, error).
CHARGE_COMMAND_STOP = 2  # charging -> stop is offered
CHARGE_COMMAND_PLAY = 3  # paused -> play (resume) is offered

CHARGE_COMMAND_LABELS: dict[int, str] = {
    CHARGE_COMMAND_STOP: "stop",
    CHARGE_COMMAND_PLAY: "play",
}
