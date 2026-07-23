"""Authentication against the Daze Cognito backend.

Strategy selection: pending confirmation from scripts/auth_spike.py. This module
implements CognitoDirectAuthStrategy (USER_PASSWORD_AUTH via the plain Cognito
Identity Provider API) as the primary path, since it needs no HTML scraping and no
extra dependency beyond aiohttp. If the spike shows the app client rejects direct
password auth, CognitoHostedLoginAuthStrategy needs to be implemented to script the
Managed Login hosted page instead (see the plan's auth spike section for what that
involves) - it is intentionally left unimplemented until we know it's needed.

Callers (api.py, coordinator.py, config_flow.py) only ever talk to DazeAuth; they
never know which strategy is in use.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any, Awaitable, Callable, Protocol

import aiohttp

from .const import COGNITO_CLIENT_ID, COGNITO_REGION, TOKEN_REFRESH_LEEWAY_SECONDS
from .exceptions import DazeAuthError, DazeCannotConnectError, DazeInvalidAuthError

COGNITO_IDP_ENDPOINT = f"https://cognito-idp.{COGNITO_REGION}.amazonaws.com/"

__all__ = [
    "COGNITO_IDP_ENDPOINT",
    "DazeAuthError",
    "DazeInvalidAuthError",
    "DazeCannotConnectError",
    "TokenSet",
    "DazeAuthStrategy",
    "CognitoDirectAuthStrategy",
    "CognitoHostedLoginAuthStrategy",
    "DazeAuth",
]


@dataclass
class TokenSet:
    access_token: str
    id_token: str
    refresh_token: str
    expires_at: float  # absolute epoch seconds

    @property
    def needs_refresh(self) -> bool:
        return time.time() >= self.expires_at - TOKEN_REFRESH_LEEWAY_SECONDS

    def as_dict(self) -> dict[str, Any]:
        return {
            "access_token": self.access_token,
            "id_token": self.id_token,
            "refresh_token": self.refresh_token,
            "expires_at": self.expires_at,
        }

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "TokenSet":
        return cls(
            access_token=raw["access_token"],
            id_token=raw["id_token"],
            refresh_token=raw["refresh_token"],
            expires_at=raw["expires_at"],
        )


class DazeAuthStrategy(Protocol):
    async def async_login(
        self, session: aiohttp.ClientSession, email: str, password: str
    ) -> TokenSet: ...

    async def async_refresh(
        self, session: aiohttp.ClientSession, refresh_token: str
    ) -> TokenSet: ...


def _auth_result_to_token_set(auth_result: dict[str, Any], *, fallback_refresh_token: str | None = None) -> TokenSet:
    now = time.time()
    refresh_token = auth_result.get("RefreshToken", fallback_refresh_token)
    if refresh_token is None:
        raise DazeInvalidAuthError("Cognito response did not include a refresh token")
    return TokenSet(
        access_token=auth_result["AccessToken"],
        id_token=auth_result["IdToken"],
        refresh_token=refresh_token,
        expires_at=now + auth_result["ExpiresIn"],
    )


class CognitoDirectAuthStrategy:
    """Strategy A: raw Cognito Identity Provider API, USER_PASSWORD_AUTH flow.

    No SRP math, no HTML scraping - just two JSON POSTs to cognito-idp. Confirmed
    working end-to-end by scripts/auth_spike.py against the real backend before
    shipping this in v1 (see auth_spike output / plan notes for the confirmation).
    """

    async def _call(
        self, session: aiohttp.ClientSession, target: str, body: dict[str, Any]
    ) -> dict[str, Any]:
        try:
            async with session.post(
                COGNITO_IDP_ENDPOINT,
                json=body,
                headers={
                    "Content-Type": "application/x-amz-json-1.1",
                    "X-Amz-Target": f"AWSCognitoIdentityProviderService.{target}",
                },
                timeout=aiohttp.ClientTimeout(total=15),
            ) as resp:
                try:
                    payload = await resp.json(content_type=None)
                except ValueError as err:
                    text = await resp.text()
                    raise DazeCannotConnectError(
                        f"Non-JSON response (HTTP {resp.status}): {text[:300]}"
                    ) from err
                if resp.status != 200:
                    error_type = payload.get("__type", "")
                    message = payload.get("message", str(payload))
                    if "NotAuthorized" in error_type or "UserNotFound" in error_type:
                        raise DazeInvalidAuthError(message)
                    raise DazeCannotConnectError(f"{error_type}: {message}")
                return payload
        except aiohttp.ClientError as err:
            raise DazeCannotConnectError(str(err)) from err

    async def async_login(
        self, session: aiohttp.ClientSession, email: str, password: str
    ) -> TokenSet:
        payload = await self._call(
            session,
            "InitiateAuth",
            {
                "ClientId": COGNITO_CLIENT_ID,
                "AuthFlow": "USER_PASSWORD_AUTH",
                "AuthParameters": {"USERNAME": email, "PASSWORD": password},
            },
        )
        if "ChallengeName" in payload:
            raise DazeInvalidAuthError(
                f"Unexpected Cognito challenge: {payload['ChallengeName']}"
            )
        return _auth_result_to_token_set(payload["AuthenticationResult"])

    async def async_refresh(
        self, session: aiohttp.ClientSession, refresh_token: str
    ) -> TokenSet:
        payload = await self._call(
            session,
            "InitiateAuth",
            {
                "ClientId": COGNITO_CLIENT_ID,
                "AuthFlow": "REFRESH_TOKEN_AUTH",
                "AuthParameters": {"REFRESH_TOKEN": refresh_token},
            },
        )
        return _auth_result_to_token_set(
            payload["AuthenticationResult"], fallback_refresh_token=refresh_token
        )


class CognitoHostedLoginAuthStrategy:
    """Strategy B (fallback, NOT YET IMPLEMENTED): script the Cognito Managed Login
    hosted page (PKCE + CSRF scraped from live HTML + oauth2/token exchange).

    Only implement this if scripts/auth_spike.py shows USER_PASSWORD_AUTH and
    USER_SRP_AUTH are both rejected by the app client. See the plan's spike section
    for the exact steps (GET /oauth2/authorize -> GET /login -> extract CSRF from
    the live HTML -> POST /login with csrf (+ cognitoAsfData if required) -> read
    the auth code from the x-remix-redirect response header -> POST /oauth2/token).
    """

    async def async_login(
        self, session: aiohttp.ClientSession, email: str, password: str
    ) -> TokenSet:
        raise NotImplementedError(
            "Hosted login strategy not needed - USER_PASSWORD_AUTH works "
            "(see scripts/auth_spike.py). Implement this only if that changes."
        )

    async def async_refresh(
        self, session: aiohttp.ClientSession, refresh_token: str
    ) -> TokenSet:
        raise NotImplementedError


class DazeAuth:
    """Facade used by api.py/coordinator.py/config_flow.py. Hides the strategy."""

    def __init__(
        self,
        session: aiohttp.ClientSession,
        strategy: DazeAuthStrategy,
        tokens: TokenSet | None = None,
        token_update_callback: Callable[[TokenSet], Awaitable[None]] | None = None,
    ) -> None:
        self._session = session
        self._strategy = strategy
        self._tokens = tokens
        self._token_update_callback = token_update_callback

    @property
    def tokens(self) -> TokenSet | None:
        return self._tokens

    async def async_login(self, email: str, password: str) -> TokenSet:
        self._tokens = await self._strategy.async_login(self._session, email, password)
        await self._notify_token_update()
        return self._tokens

    async def async_get_access_token(self) -> str:
        """Return a valid access token, refreshing proactively if near expiry."""
        if self._tokens is None:
            raise DazeAuthError("async_login/set tokens before requesting an access token")
        if self._tokens.needs_refresh:
            await self.async_refresh()
        return self._tokens.access_token

    async def async_refresh(self) -> TokenSet:
        if self._tokens is None:
            raise DazeAuthError("no tokens to refresh")
        self._tokens = await self._strategy.async_refresh(
            self._session, self._tokens.refresh_token
        )
        await self._notify_token_update()
        return self._tokens

    async def _notify_token_update(self) -> None:
        if self._token_update_callback is not None and self._tokens is not None:
            await self._token_update_callback(self._tokens)
