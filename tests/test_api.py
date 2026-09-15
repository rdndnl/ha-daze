from __future__ import annotations

import time
from unittest.mock import AsyncMock

import pytest
from homeassistant.exceptions import ConfigEntryAuthFailed
from pytest_homeassistant_custom_component.test_util.aiohttp import AiohttpClientMockResponse
from yarl import URL

from custom_components.daze.api import DazeApiClient, DazeCannotConnectError
from custom_components.daze.auth import (
    COGNITO_IDP_ENDPOINT,
    CognitoDirectAuthStrategy,
    DazeAuth,
    TokenSet,
)
from custom_components.daze.const import REQUEST_TIMEOUT_RETRIES, WEBAPI_BASE_URL


def _fresh_auth(session, token: str = "valid-token") -> DazeAuth:
    tokens = TokenSet(
        access_token=token, id_token="i", refresh_token="r", expires_at=time.time() + 3600
    )
    strategy = AsyncMock()
    return DazeAuth(session, strategy, tokens=tokens)


def _sequential_responses(*responses):
    """side_effect callable returning a different canned response on each call."""
    remaining = list(responses)

    async def _side_effect(method, url, data):
        return remaining.pop(0)

    return _side_effect


async def test_get_user_profile(hass, aioclient_mock, user_profile_data):
    aioclient_mock.get(
        f"{WEBAPI_BASE_URL}/v3/users/a%40b.com/",
        params={"appName": 1},
        json={"data": user_profile_data, "message": "", "errors": []},
    )
    session = aioclient_mock.create_session(hass.loop)
    try:
        api = DazeApiClient(session, _fresh_auth(session))
        profile = await api.async_get_user_profile("a@b.com")
    finally:
        await session.close()

    assert profile["identityId"] == user_profile_data["identityId"]


async def test_get_networks(hass, aioclient_mock, networks_data):
    aioclient_mock.get(
        f"{WEBAPI_BASE_URL}/v3/users/a%40b.com/networks",
        params={"includeStats": "true"},
        json={"data": networks_data, "message": "", "errors": []},
    )
    session = aioclient_mock.create_session(hass.loop)
    try:
        api = DazeApiClient(session, _fresh_auth(session))
        networks = await api.async_get_networks("a@b.com")
    finally:
        await session.close()

    assert len(networks) == 1
    assert networks[0].uid == "00000000-0000-0000-0000-000000000003"


async def test_socket_remote_info_404_returns_none(hass, aioclient_mock):
    aioclient_mock.get(
        f"{WEBAPI_BASE_URL}/v3/sockets/MISSING/remoteInfo",
        params={"includeEcoInfo": "true", "includeNextSchedule": "true"},
        status=404,
    )
    session = aioclient_mock.create_session(hass.loop)
    try:
        api = DazeApiClient(session, _fresh_auth(session))
        result = await api.async_get_socket_remote_info("MISSING")
    finally:
        await session.close()

    assert result is None


async def test_401_triggers_single_refresh_then_succeeds(hass, aioclient_mock, user_profile_data):
    url = URL(f"{WEBAPI_BASE_URL}/v3/users/a%40b.com/").with_query({"appName": 1})
    ok_response = AiohttpClientMockResponse(
        method="get",
        url=url,
        json={"data": user_profile_data, "message": "", "errors": []},
    )
    unauthorized_response = AiohttpClientMockResponse(method="get", url=url, status=401)
    aioclient_mock.get(url, side_effect=_sequential_responses(unauthorized_response, ok_response))

    session = aioclient_mock.create_session(hass.loop)
    try:
        tokens = TokenSet(
            access_token="expired", id_token="i", refresh_token="r", expires_at=time.time() + 3600
        )
        strategy = AsyncMock()
        strategy.async_refresh.return_value = TokenSet(
            access_token="renewed", id_token="i", refresh_token="r", expires_at=time.time() + 3600
        )
        auth = DazeAuth(session, strategy, tokens=tokens)
        api = DazeApiClient(session, auth)

        profile = await api.async_get_user_profile("a@b.com")
    finally:
        await session.close()

    assert profile["identityId"] == user_profile_data["identityId"]
    strategy.async_refresh.assert_called_once()


async def test_401_twice_raises_config_entry_auth_failed(hass, aioclient_mock):
    url = URL(f"{WEBAPI_BASE_URL}/v3/users/a%40b.com/").with_query({"appName": 1})
    aioclient_mock.get(url, status=401)

    session = aioclient_mock.create_session(hass.loop)
    try:
        tokens = TokenSet(
            access_token="expired", id_token="i", refresh_token="r", expires_at=time.time() + 3600
        )
        strategy = AsyncMock()
        strategy.async_refresh.return_value = TokenSet(
            access_token="still-bad", id_token="i", refresh_token="r", expires_at=time.time() + 3600
        )
        auth = DazeAuth(session, strategy, tokens=tokens)
        api = DazeApiClient(session, auth)

        with pytest.raises(ConfigEntryAuthFailed):
            await api.async_get_user_profile("a@b.com")
    finally:
        await session.close()


async def test_timeout_raises_cannot_connect(hass, aioclient_mock):
    """Timeouts must leave api.py as DazeCannotConnectError, like any other network fault.

    asyncio.TimeoutError is the builtin TimeoutError on 3.11+ and is *not* an
    aiohttp.ClientError, so before _request grew an explicit branch for it a timeout
    escaped the module untouched - config_flow reported "unknown" instead of
    "cannot_connect", and the coordinator only caught it via HA's generic fallback.
    """
    aioclient_mock.get(
        f"{WEBAPI_BASE_URL}/v3/users/a%40b.com/",
        params={"appName": 1},
        exc=TimeoutError(),
    )
    session = aioclient_mock.create_session(hass.loop)
    try:
        api = DazeApiClient(session, _fresh_auth(session))
        with pytest.raises(DazeCannotConnectError, match="timed out"):
            await api.async_get_user_profile("a@b.com")
    finally:
        await session.close()

    assert len(aioclient_mock.mock_calls) == REQUEST_TIMEOUT_RETRIES + 1


async def test_timeout_is_retried_then_succeeds(hass, aioclient_mock, user_profile_data):
    url = URL(f"{WEBAPI_BASE_URL}/v3/users/a%40b.com/").with_query({"appName": 1})
    timed_out = AiohttpClientMockResponse(method="get", url=url, exc=TimeoutError())
    ok_response = AiohttpClientMockResponse(
        method="get",
        url=url,
        json={"data": user_profile_data, "message": "", "errors": []},
    )
    aioclient_mock.get(url, side_effect=_sequential_responses(timed_out, ok_response))

    session = aioclient_mock.create_session(hass.loop)
    try:
        api = DazeApiClient(session, _fresh_auth(session))
        profile = await api.async_get_user_profile("a@b.com")
    finally:
        await session.close()

    assert profile["identityId"] == user_profile_data["identityId"]
    assert len(aioclient_mock.mock_calls) == 2


async def test_timeout_and_401_retry_budgets_are_independent(
    hass, aioclient_mock, user_profile_data
):
    """A timeout must not consume the single forced-refresh attempt reserved for a 401."""
    url = URL(f"{WEBAPI_BASE_URL}/v3/users/a%40b.com/").with_query({"appName": 1})
    timed_out = AiohttpClientMockResponse(method="get", url=url, exc=TimeoutError())
    unauthorized_response = AiohttpClientMockResponse(method="get", url=url, status=401)
    ok_response = AiohttpClientMockResponse(
        method="get",
        url=url,
        json={"data": user_profile_data, "message": "", "errors": []},
    )
    aioclient_mock.get(
        url,
        side_effect=_sequential_responses(timed_out, unauthorized_response, ok_response),
    )

    session = aioclient_mock.create_session(hass.loop)
    try:
        strategy = AsyncMock()
        strategy.async_refresh.return_value = TokenSet(
            access_token="renewed", id_token="i", refresh_token="r", expires_at=time.time() + 3600
        )
        auth = DazeAuth(
            session,
            strategy,
            tokens=TokenSet(
                access_token="expired",
                id_token="i",
                refresh_token="r",
                expires_at=time.time() + 3600,
            ),
        )
        api = DazeApiClient(session, auth)

        profile = await api.async_get_user_profile("a@b.com")
    finally:
        await session.close()

    assert profile["identityId"] == user_profile_data["identityId"]
    strategy.async_refresh.assert_called_once()
    assert len(aioclient_mock.mock_calls) == 3


async def test_timeout_during_token_refresh_does_not_trigger_reauth(hass, aioclient_mock):
    """A Cognito refresh that times out is a network fault, not an auth failure.

    DazeCannotConnectError is deliberately not a DazeAuthError: if it were, _request
    would map it onto ConfigEntryAuthFailed and HA would ask the user to re-enter their
    password over a transient network blip.
    """
    aioclient_mock.post(COGNITO_IDP_ENDPOINT, exc=TimeoutError())

    session = aioclient_mock.create_session(hass.loop)
    try:
        expired = TokenSet(
            access_token="stale", id_token="i", refresh_token="r", expires_at=time.time() - 1
        )
        auth = DazeAuth(session, CognitoDirectAuthStrategy(), tokens=expired)
        api = DazeApiClient(session, auth)

        with pytest.raises(DazeCannotConnectError, match="timed out"):
            await api.async_get_user_profile("a@b.com")
    finally:
        await session.close()


async def test_server_error_raises_cannot_connect(hass, aioclient_mock):
    aioclient_mock.get(
        f"{WEBAPI_BASE_URL}/v3/users/a%40b.com/",
        params={"appName": 1},
        status=500,
        text="boom",
    )
    session = aioclient_mock.create_session(hass.loop)
    try:
        api = DazeApiClient(session, _fresh_auth(session))
        with pytest.raises(DazeCannotConnectError):
            await api.async_get_user_profile("a@b.com")
    finally:
        await session.close()


async def test_get_command_authorizations(hass, aioclient_mock, command_authorizations_data):
    aioclient_mock.get(
        f"{WEBAPI_BASE_URL}/v3/evses/TEST0000001/commandAuthorizations",
        params={"checkMode": "RPC"},
        json={"data": command_authorizations_data, "message": "", "errors": []},
    )
    session = aioclient_mock.create_session(hass.loop)
    try:
        api = DazeApiClient(session, _fresh_auth(session))
        result = await api.async_get_command_authorizations("TEST0000001")
    finally:
        await session.close()

    assert result["socketAvailableChargeCommand"][0]["availableChargeCommand"] == 3


@pytest.mark.parametrize(
    ("method_name", "command"),
    [
        ("async_start_charge", "startcharge"),
        ("async_stop_charge", "stopcharge"),
        ("async_play_charge", "playcharge"),
    ],
)
async def test_charge_commands_post_to_socket_path(hass, aioclient_mock, method_name, command):
    """Commands go to /v3/sockets/{socket serial}/commands/{command} with an empty body.

    The backend answers with no `data`, so the methods return None and the caller is
    expected to refresh rather than read anything back.
    """
    aioclient_mock.post(
        f"{WEBAPI_BASE_URL}/v3/sockets/TEST0000001/commands/{command}",
        json={"message": "", "errors": []},
    )
    session = aioclient_mock.create_session(hass.loop)
    try:
        api = DazeApiClient(session, _fresh_auth(session))
        result = await getattr(api, method_name)("TEST0000001")
    finally:
        await session.close()

    assert result is None
    assert aioclient_mock.call_count == 1
    method, url, data, headers = aioclient_mock.mock_calls[0]
    assert method == "POST"
    assert url.path == f"/v3/sockets/TEST0000001/commands/{command}"
    assert data == {}
    assert headers["Authorization"] == "Bearer valid-token"


async def test_charge_command_http_error_raises_cannot_connect(hass, aioclient_mock):
    aioclient_mock.post(
        f"{WEBAPI_BASE_URL}/v3/sockets/TEST0000001/commands/startcharge",
        status=500,
        text="boom",
    )
    session = aioclient_mock.create_session(hass.loop)
    try:
        api = DazeApiClient(session, _fresh_auth(session))
        with pytest.raises(DazeCannotConnectError, match="HTTP 500"):
            await api.async_start_charge("TEST0000001")
    finally:
        await session.close()
