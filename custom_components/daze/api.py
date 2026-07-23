"""REST client for the Daze backend (webapi.dazeservice.com).

No auth strategy logic here - that lives in auth.py. This module only knows how to
shape requests/responses and how to react to a 401 (refresh once via DazeAuth, retry
once, then give up and let the caller's config entry go into reauth).
"""

from __future__ import annotations

import logging
from typing import Any
from urllib.parse import quote

import aiohttp
from homeassistant.exceptions import ConfigEntryAuthFailed

from .auth import DazeAuth
from .const import WEBAPI_BASE_URL
from .exceptions import DazeAuthError, DazeCannotConnectError
from .models import DazeEvse, DazeNetwork

_LOGGER = logging.getLogger(__name__)


class DazeApiClient:
    def __init__(self, session: aiohttp.ClientSession, auth: DazeAuth) -> None:
        self._session = session
        self._auth = auth

    async def _request(self, method: str, path: str, **kwargs: Any) -> Any:
        url = f"{WEBAPI_BASE_URL}{path}"
        for attempt in (1, 2):
            try:
                token = await self._auth.async_get_access_token()
            except DazeAuthError as err:
                raise ConfigEntryAuthFailed(str(err)) from err

            try:
                async with self._session.request(
                    method,
                    url,
                    headers={"Authorization": f"Bearer {token}"},
                    timeout=aiohttp.ClientTimeout(total=15),
                    **kwargs,
                ) as resp:
                    if resp.status == 401 and attempt == 1:
                        _LOGGER.debug("401 from %s, forcing token refresh and retrying once", path)
                        try:
                            await self._auth.async_refresh()
                        except DazeAuthError as err:
                            raise ConfigEntryAuthFailed(str(err)) from err
                        continue
                    if resp.status == 401:
                        raise ConfigEntryAuthFailed(f"Backend rejected refreshed token for {path}")
                    if resp.status == 404:
                        return None
                    if resp.status >= 400:
                        text = await resp.text()
                        raise DazeCannotConnectError(f"{method} {path} -> HTTP {resp.status}: {text[:300]}")
                    payload = await resp.json()
                    return payload.get("data")
            except aiohttp.ClientError as err:
                raise DazeCannotConnectError(str(err)) from err

        raise DazeCannotConnectError(f"Unreachable: exhausted retries for {path}")

    async def async_get_user_profile(self, email: str) -> dict[str, Any]:
        return await self._request("GET", f"/v3/users/{quote(email)}/", params={"appName": 1})

    async def async_get_networks(self, email: str) -> list[DazeNetwork]:
        raw_list = await self._request(
            "GET", f"/v3/users/{quote(email)}/networks", params={"includeStats": "true"}
        )
        return [DazeNetwork.from_dict(raw) for raw in (raw_list or [])]

    async def async_get_network_evses(self, network_uid: str) -> list[DazeEvse]:
        raw_list = await self._request(
            "GET", f"/v3/networks/{network_uid}/evses", params={"includeEcoInfo": "false"}
        )
        return [DazeEvse.from_dict(raw) for raw in (raw_list or [])]

    async def async_get_socket_remote_info(self, serial_number: str) -> dict[str, Any] | None:
        return await self._request(
            "GET",
            f"/v3/sockets/{serial_number}/remoteInfo",
            params={"includeEcoInfo": "true", "includeNextSchedule": "true"},
        )
