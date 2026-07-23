from __future__ import annotations

import time
from unittest.mock import AsyncMock

import pytest
from homeassistant.exceptions import ConfigEntryAuthFailed
from pytest_homeassistant_custom_component.test_util.aiohttp import AiohttpClientMockResponse
from yarl import URL

from custom_components.daze.api import DazeApiClient, DazeCannotConnectError
from custom_components.daze.auth import DazeAuth, TokenSet
from custom_components.daze.const import WEBAPI_BASE_URL


def _fresh_auth(session, token: str = "valid-token") -> DazeAuth:
    tokens = TokenSet(access_token=token, id_token="i", refresh_token="r", expires_at=time.time() + 3600)
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
    assert networks[0].uid == "37a2a379-07f1-488b-81d5-8946e662f72a"


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
        tokens = TokenSet(access_token="expired", id_token="i", refresh_token="r", expires_at=time.time() + 3600)
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
        tokens = TokenSet(access_token="expired", id_token="i", refresh_token="r", expires_at=time.time() + 3600)
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
