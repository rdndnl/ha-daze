"""Entry setup/update behaviour.

The regression these tests guard: _async_persist_tokens writes the refreshed token
set back onto the config entry every ~55 min, which fires the entry update listener.
When that listener reloaded the entry, every entity was torn down and rebuilt, so all
Daze sensors flickered to `unavailable` for about a second on each token refresh.
"""

from __future__ import annotations

from datetime import timedelta

import pytest
from homeassistant.const import CONF_EMAIL
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.daze.const import (
    CONF_SCAN_INTERVAL,
    CONF_TOKEN,
    DOMAIN,
    WEBAPI_BASE_URL,
)

EMAIL = "a@b.com"
NETWORK_UID = "00000000-0000-0000-0000-000000000003"
EVSE_SERIAL = "TEST0000001"
SOCKET_SERIAL = "TEST0000001"


@pytest.fixture(autouse=True)
def _enable_custom_integrations(enable_custom_integrations):
    yield


def _mock_backend(aioclient_mock, networks_data, evses_data, remote_info_data):
    aioclient_mock.get(
        f"{WEBAPI_BASE_URL}/v3/users/a%40b.com/networks",
        json={"data": networks_data, "message": "", "errors": []},
    )
    aioclient_mock.get(
        f"{WEBAPI_BASE_URL}/v3/networks/{NETWORK_UID}/evses",
        json={"data": evses_data, "message": "", "errors": []},
    )
    aioclient_mock.get(
        f"{WEBAPI_BASE_URL}/v3/sockets/{SOCKET_SERIAL}/remoteInfo",
        json={"data": remote_info_data, "message": "", "errors": []},
    )
    aioclient_mock.get(
        f"{WEBAPI_BASE_URL}/v3/evses/{EVSE_SERIAL}/commandAuthorizations",
        json={
            "data": {
                "evseSerialNumber": EVSE_SERIAL,
                "socketAvailableChargeCommand": [
                    {"socketSerialNumber": SOCKET_SERIAL, "availableChargeCommand": 3}
                ],
            },
            "message": "",
            "errors": [],
        },
    )


async def _setup_entry(hass, aioclient_mock, networks_data, evses_data, remote_info_data):
    _mock_backend(aioclient_mock, networks_data, evses_data, remote_info_data)
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id="identity-1",
        data={
            CONF_EMAIL: EMAIL,
            # expires_at far in the future: no Cognito call during these tests.
            CONF_TOKEN: {
                "access_token": "at",
                "id_token": "it",
                "refresh_token": "rt",
                "expires_at": 9_999_999_999,
            },
        },
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry


async def test_token_persistence_does_not_reload_entry(
    hass, aioclient_mock, networks_data, evses_data, remote_info_data
):
    entry = await _setup_entry(hass, aioclient_mock, networks_data, evses_data, remote_info_data)
    coordinator = hass.data[DOMAIN][entry.entry_id]

    tariff_state = hass.states.get(f"sensor.{NETWORK_UID.replace('-', '_')}_energy_tariff")
    if tariff_state is None:  # entity_id layout depends on the network's name
        tariff_state = next(
            state
            for state in hass.states.async_all("sensor")
            if state.entity_id.endswith("_energy_tariff")
        )
    assert tariff_state.state != "unavailable"

    # Simulate what _async_persist_tokens does after a proactive Cognito refresh.
    hass.config_entries.async_update_entry(
        entry,
        data={
            **entry.data,
            CONF_TOKEN: {
                "access_token": "at2",
                "id_token": "it2",
                "refresh_token": "rt",
                "expires_at": 9_999_999_999,
            },
        },
    )
    await hass.async_block_till_done()

    # Same coordinator instance => the entry was not torn down and set up again,
    # so no entity ever went through an unavailable state.
    assert hass.data[DOMAIN][entry.entry_id] is coordinator
    assert hass.states.get(tariff_state.entity_id).state == tariff_state.state


async def test_options_update_applies_scan_interval_in_place(
    hass, aioclient_mock, networks_data, evses_data, remote_info_data
):
    entry = await _setup_entry(hass, aioclient_mock, networks_data, evses_data, remote_info_data)
    coordinator = hass.data[DOMAIN][entry.entry_id]
    assert coordinator.update_interval == timedelta(seconds=60)

    hass.config_entries.async_update_entry(entry, options={CONF_SCAN_INTERVAL: 120})
    await hass.async_block_till_done()

    assert hass.data[DOMAIN][entry.entry_id] is coordinator
    assert coordinator.update_interval == timedelta(seconds=120)
