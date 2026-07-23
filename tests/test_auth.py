from __future__ import annotations

import time

import pytest

from custom_components.daze.auth import (
    COGNITO_IDP_ENDPOINT,
    CognitoDirectAuthStrategy,
    DazeAuth,
    DazeInvalidAuthError,
    TokenSet,
)


def test_token_set_needs_refresh():
    fresh = TokenSet(access_token="a", id_token="i", refresh_token="r", expires_at=time.time() + 3600)
    assert fresh.needs_refresh is False

    stale = TokenSet(access_token="a", id_token="i", refresh_token="r", expires_at=time.time() + 60)
    assert stale.needs_refresh is True


def test_token_set_roundtrip():
    ts = TokenSet(access_token="a", id_token="i", refresh_token="r", expires_at=123.0)
    assert TokenSet.from_dict(ts.as_dict()) == ts


async def test_direct_auth_strategy_login_success(hass, aioclient_mock):
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
    session = aioclient_mock.create_session(hass.loop)
    try:
        strategy = CognitoDirectAuthStrategy()
        tokens = await strategy.async_login(session, "a@b.com", "pw")
    finally:
        await session.close()

    assert tokens.access_token == "at"
    assert tokens.refresh_token == "rt"


async def test_direct_auth_strategy_login_rejected(hass, aioclient_mock):
    aioclient_mock.post(
        COGNITO_IDP_ENDPOINT,
        status=400,
        json={"__type": "NotAuthorizedException", "message": "Incorrect username or password."},
    )
    session = aioclient_mock.create_session(hass.loop)
    try:
        strategy = CognitoDirectAuthStrategy()
        with pytest.raises(DazeInvalidAuthError):
            await strategy.async_login(session, "a@b.com", "wrong")
    finally:
        await session.close()


async def test_refresh_reuses_refresh_token_when_not_rotated(hass, aioclient_mock):
    aioclient_mock.post(
        COGNITO_IDP_ENDPOINT,
        json={
            "AuthenticationResult": {
                "AccessToken": "new-at",
                "IdToken": "new-it",
                "ExpiresIn": 3600,
                # No RefreshToken in the response - Cognito's default behaviour.
            }
        },
    )
    session = aioclient_mock.create_session(hass.loop)
    try:
        strategy = CognitoDirectAuthStrategy()
        tokens = await strategy.async_refresh(session, "old-refresh-token")
    finally:
        await session.close()

    assert tokens.access_token == "new-at"
    assert tokens.refresh_token == "old-refresh-token"


async def test_daze_auth_proactive_refresh(hass, aioclient_mock):
    calls = {"count": 0}

    async def _persist(tokens: TokenSet) -> None:
        calls["count"] += 1

    session = aioclient_mock.create_session(hass.loop)
    try:
        strategy = CognitoDirectAuthStrategy()
        stale_tokens = TokenSet(
            access_token="stale", id_token="i", refresh_token="r", expires_at=time.time() + 1
        )
        auth = DazeAuth(session, strategy, tokens=stale_tokens, token_update_callback=_persist)

        aioclient_mock.post(
            COGNITO_IDP_ENDPOINT,
            json={
                "AuthenticationResult": {
                    "AccessToken": "fresh",
                    "IdToken": "it",
                    "RefreshToken": "r",
                    "ExpiresIn": 3600,
                }
            },
        )
        token = await auth.async_get_access_token()
    finally:
        await session.close()

    assert token == "fresh"
    assert calls["count"] == 1
