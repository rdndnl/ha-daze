"""REST client for the Daze backend (webapi.dazeservice.com).

No auth strategy logic here - that lives in auth.py. This module only knows how to
shape requests/responses and how to react to a 401 (refresh once via DazeAuth, retry
once, then give up and let the caller's config entry go into reauth).

Every connectivity failure leaves this module as a DazeCannotConnectError - that is the
contract callers rely on. Timeouts included: see the TimeoutError branch in _request.
"""

from __future__ import annotations

import logging
from typing import Any
from urllib.parse import quote

import aiohttp
from homeassistant.exceptions import ConfigEntryAuthFailed

from .auth import DazeAuth
from .const import REQUEST_TIMEOUT, REQUEST_TIMEOUT_RETRIES, WEBAPI_BASE_URL
from .exceptions import DazeAuthError, DazeCannotConnectError
from .models import DazeEvse, DazeNetwork

_LOGGER = logging.getLogger(__name__)


class DazeApiClient:
    def __init__(self, session: aiohttp.ClientSession, auth: DazeAuth) -> None:
        self._session = session
        self._auth = auth

    async def _request(self, method: str, path: str, **kwargs: Any) -> Any:
        """Perform one authenticated REST call.

        Two retry budgets, deliberately kept separate: `refreshed` allows exactly one
        forced token refresh + retry on a 401, `retries_left` allows a few immediate
        retries on a timeout. A timeout is a transient network fault, not an auth
        problem, so it must not eat the 401 budget (and vice versa).
        """
        url = f"{WEBAPI_BASE_URL}{path}"
        refreshed = False
        retries_left = REQUEST_TIMEOUT_RETRIES
        while True:
            try:
                token = await self._auth.async_get_access_token()
            except DazeAuthError as err:
                raise ConfigEntryAuthFailed(str(err)) from err

            try:
                async with self._session.request(
                    method,
                    url,
                    headers={"Authorization": f"Bearer {token}"},
                    timeout=REQUEST_TIMEOUT,
                    **kwargs,
                ) as resp:
                    if resp.status == 401:
                        if refreshed:
                            raise ConfigEntryAuthFailed(
                                f"Backend rejected refreshed token for {path}"
                            )
                        _LOGGER.debug("401 from %s, forcing token refresh and retrying once", path)
                        try:
                            await self._auth.async_refresh()
                        except DazeAuthError as err:
                            raise ConfigEntryAuthFailed(str(err)) from err
                        refreshed = True
                        continue
                    if resp.status == 404:
                        return None
                    if resp.status >= 400:
                        text = await resp.text()
                        raise DazeCannotConnectError(
                            f"{method} {path} -> HTTP {resp.status}: {text[:300]}"
                        )
                    payload = await resp.json()
                    return payload.get("data")
            except TimeoutError as err:
                # asyncio.TimeoutError *is* the builtin TimeoutError on 3.11+, and it is
                # NOT an aiohttp.ClientError - so without this branch a timeout escaped
                # _request entirely, breaking the "connectivity failure ->
                # DazeCannotConnectError" contract: config_flow fell through to its
                # generic `except Exception` (or, in the reauth step, to nothing at all)
                # and the coordinator only caught it via Home Assistant's own fallback.
                # Must come before aiohttp.ClientError: aiohttp.ServerTimeoutError
                # inherits from both, and this branch gives it the better message.
                if retries_left:
                    retries_left -= 1
                    _LOGGER.debug(
                        "Timeout on %s %s, retrying (%d left)", method, path, retries_left
                    )
                    continue
                raise DazeCannotConnectError(
                    f"{method} {path} timed out after {REQUEST_TIMEOUT.total}s"
                ) from err
            except aiohttp.ClientError as err:
                raise DazeCannotConnectError(f"{method} {path}: {err}") from err

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

    async def async_get_command_authorizations(self, evse_serial: str) -> dict[str, Any] | None:
        """Which charge command each socket of this EVSE currently accepts.

        One call answers for every socket of the wallbox, so the coordinator fetches
        this per EVSE rather than per socket.
        """
        return await self._request(
            "GET",
            f"/v3/evses/{evse_serial}/commandAuthorizations",
            params={"checkMode": "RPC"},
        )

    # Charge commands are addressed by the SOCKET serial number (the /v3/sockets/...
    # paths the vendor portal itself calls), not by the EVSE serial. The backend
    # answers 200 with an empty `data`, so these return nothing on purpose: callers
    # must not infer the new state from the response and should refresh instead.

    async def async_start_charge(self, serial_number: str) -> None:
        """Open a new charging session on one socket.

        This also arms the authorization window (~60s observed) during which the cable
        has to be plugged in. It does NOT resume a paused session - see
        async_play_charge.
        """
        await self._request("POST", f"/v3/sockets/{serial_number}/commands/startcharge", json={})

    async def async_stop_charge(self, serial_number: str) -> None:
        """Pause the running charging session on one socket.

        The session stays open: the socket then reports availableChargeCommand
        CHARGE_COMMAND_PLAY and only playcharge picks it back up.
        """
        await self._request("POST", f"/v3/sockets/{serial_number}/commands/stopcharge", json={})

    async def async_play_charge(self, serial_number: str) -> None:
        """Resume a paused charging session on one socket.

        Distinct from startcharge: after a stopcharge the wallbox silently ignores
        startcharge, which is exactly the "start does nothing after stop" symptom.
        """
        await self._request("POST", f"/v3/sockets/{serial_number}/commands/playcharge", json={})
