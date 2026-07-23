from __future__ import annotations

import pytest
from homeassistant import config_entries
from homeassistant.const import CONF_EMAIL, CONF_PASSWORD
from homeassistant.data_entry_flow import FlowResultType

from custom_components.daze.auth import COGNITO_IDP_ENDPOINT
from custom_components.daze.const import CONF_TOKEN, DOMAIN, WEBAPI_BASE_URL


@pytest.fixture(autouse=True)
def _enable_custom_integrations(enable_custom_integrations):
    yield


def _mock_successful_login(aioclient_mock, user_profile_data):
    aioclient_mock.post(
        COGNITO_IDP_ENDPOINT,
        json={
            "AuthenticationResult": {
                "AccessToken": "at",
                "IdToken": "it",
                "RefreshToken": "rt",
                "ExpiresIn": 3600,
            }
        },
    )
    aioclient_mock.get(
        f"{WEBAPI_BASE_URL}/v3/users/a%40b.com/",
        params={"appName": 1},
        json={"data": user_profile_data, "message": "", "errors": []},
    )


async def test_user_flow_success(hass, aioclient_mock, user_profile_data):
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    assert result["type"] == FlowResultType.FORM

    _mock_successful_login(aioclient_mock, user_profile_data)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {CONF_EMAIL: "a@b.com", CONF_PASSWORD: "pw"},
    )

    assert result["type"] == FlowResultType.CREATE_ENTRY
    assert result["title"] == "a@b.com"
    assert result["data"][CONF_EMAIL] == "a@b.com"
    assert CONF_TOKEN in result["data"]
    assert result["result"].unique_id == user_profile_data["identityId"]


async def test_user_flow_invalid_auth(hass, aioclient_mock):
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )

    aioclient_mock.post(
        COGNITO_IDP_ENDPOINT,
        status=400,
        json={"__type": "NotAuthorizedException", "message": "bad creds"},
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {CONF_EMAIL: "a@b.com", CONF_PASSWORD: "wrong"},
    )

    assert result["type"] == FlowResultType.FORM
    assert result["errors"] == {"base": "invalid_auth"}


async def test_user_flow_cannot_connect(hass, aioclient_mock):
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )

    aioclient_mock.post(COGNITO_IDP_ENDPOINT, status=500, text="boom")
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {CONF_EMAIL: "a@b.com", CONF_PASSWORD: "pw"},
    )

    assert result["type"] == FlowResultType.FORM
    assert result["errors"] == {"base": "cannot_connect"}


async def test_user_flow_duplicate_account_aborts(hass, aioclient_mock, user_profile_data):
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    _mock_successful_login(aioclient_mock, user_profile_data)
    await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_EMAIL: "a@b.com", CONF_PASSWORD: "pw"}
    )

    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_EMAIL: "a@b.com", CONF_PASSWORD: "pw"}
    )

    assert result["type"] == FlowResultType.ABORT
    assert result["reason"] == "already_configured"
