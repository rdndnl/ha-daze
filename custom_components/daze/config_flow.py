"""Config flow for the Daze integration."""

from __future__ import annotations

import logging
from typing import Any

import aiohttp
import voluptuous as vol
from homeassistant.config_entries import ConfigEntry, ConfigFlow, ConfigFlowResult, OptionsFlow
from homeassistant.const import CONF_EMAIL, CONF_PASSWORD
from homeassistant.core import callback
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import DazeApiClient, DazeCannotConnectError
from .auth import (
    CognitoDirectAuthStrategy,
    DazeAuth,
    DazeInvalidAuthError,
    TokenSet,
    decode_jwt_claims,
)
from .const import (
    CONF_SCAN_INTERVAL,
    CONF_TOKEN,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
    MAX_SCAN_INTERVAL,
    MIN_SCAN_INTERVAL,
)

_LOGGER = logging.getLogger(__name__)

CONF_REFRESH_TOKEN = "refresh_token"

STEP_USER_DATA_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_EMAIL): str,
        vol.Required(CONF_PASSWORD): str,
    }
)

STEP_GOOGLE_DATA_SCHEMA = vol.Schema({vol.Required(CONF_REFRESH_TOKEN): str})


async def _authenticate(
    hass, email: str, password: str
) -> tuple[TokenSet, dict[str, Any]]:
    """Log in and fetch the profile in one go.

    Raises DazeInvalidAuthError/DazeCannotConnectError. auth.py and api.py already
    normalise timeouts into DazeCannotConnectError, but both callers below also catch
    TimeoutError explicitly: async_step_reauth_confirm has no `except Exception` safety
    net, so anything that slips through there escapes the flow handler and Home
    Assistant aborts the reauth with an opaque unknown error instead of letting the
    user retry.
    """
    session = async_get_clientsession(hass)
    auth = DazeAuth(session, CognitoDirectAuthStrategy())
    tokens = await auth.async_login(email, password)
    api = DazeApiClient(session, auth)
    profile = await api.async_get_user_profile(email)
    if profile is None:
        raise DazeCannotConnectError("empty profile response")
    return tokens, profile


def _clean_token(raw: str) -> str:
    """Strip whitespace and the quotes DevTools/JSON copy-paste tends to add."""
    return raw.strip().strip("\"'").strip()


async def _authenticate_with_refresh_token(
    hass, refresh_token: str
) -> tuple[str, TokenSet, dict[str, Any]]:
    """Sign in from a Cognito refresh token (Google/federated accounts).

    Returns (email, tokens, profile). The email comes from the ID token, because a
    Google user never types one into the form. Raises DazeInvalidAuthError for a
    rejected/expired token, DazeCannotConnectError for network trouble.
    """
    session = async_get_clientsession(hass)
    auth = DazeAuth(session, CognitoDirectAuthStrategy())
    tokens = await auth.async_login_with_refresh_token(refresh_token)
    email = decode_jwt_claims(tokens.id_token).get("email")
    if not email:
        raise DazeInvalidAuthError("ID token does not contain an email claim")
    api = DazeApiClient(session, auth)
    try:
        profile = await api.async_get_user_profile(email)
    except ConfigEntryAuthFailed as err:
        raise DazeInvalidAuthError(str(err)) from err
    if profile is None:
        raise DazeCannotConnectError("empty profile response")
    return email, tokens, profile


class DazeConfigFlow(ConfigFlow, domain=DOMAIN):
    VERSION = 1

    def __init__(self) -> None:
        self._reauth_entry: ConfigEntry | None = None

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        return self.async_show_menu(step_id="user", menu_options=["password", "google"])

    async def async_step_password(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            email = user_input[CONF_EMAIL]
            password = user_input[CONF_PASSWORD]
            try:
                tokens, profile = await _authenticate(self.hass, email, password)
            except DazeInvalidAuthError:
                errors["base"] = "invalid_auth"
            except (DazeCannotConnectError, aiohttp.ClientError, TimeoutError):
                errors["base"] = "cannot_connect"
            except Exception:
                _LOGGER.exception("Unexpected error during Daze config flow")
                errors["base"] = "unknown"
            else:
                await self.async_set_unique_id(profile["identityId"])
                self._abort_if_unique_id_configured()
                return self.async_create_entry(
                    title=email,
                    data={
                        CONF_EMAIL: email,
                        CONF_PASSWORD: password,
                        CONF_TOKEN: tokens.as_dict(),
                    },
                )

        return self.async_show_form(
            step_id="password", data_schema=STEP_USER_DATA_SCHEMA, errors=errors
        )

    async def async_step_google(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Set up an account that signs in with Google (no password available)."""
        errors: dict[str, str] = {}
        if user_input is not None:
            refresh_token = _clean_token(user_input[CONF_REFRESH_TOKEN])
            try:
                email, tokens, profile = await _authenticate_with_refresh_token(
                    self.hass, refresh_token
                )
            except DazeInvalidAuthError:
                errors["base"] = "invalid_token"
            except (DazeCannotConnectError, aiohttp.ClientError, TimeoutError):
                errors["base"] = "cannot_connect"
            except Exception:
                _LOGGER.exception("Unexpected error during Daze Google config flow")
                errors["base"] = "unknown"
            else:
                await self.async_set_unique_id(profile["identityId"])
                self._abort_if_unique_id_configured()
                # No CONF_PASSWORD on purpose: its absence marks a token-based entry,
                # which is what the reauth step below keys on.
                return self.async_create_entry(
                    title=email,
                    data={CONF_EMAIL: email, CONF_TOKEN: tokens.as_dict()},
                )

        return self.async_show_form(
            step_id="google", data_schema=STEP_GOOGLE_DATA_SCHEMA, errors=errors
        )

    async def async_step_reauth(self, entry_data: dict[str, Any]) -> ConfigFlowResult:
        self._reauth_entry = self.hass.config_entries.async_get_entry(self.context["entry_id"])
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        assert self._reauth_entry is not None
        if CONF_PASSWORD not in self._reauth_entry.data:
            return await self.async_step_reauth_google()
        if user_input is not None:
            email = self._reauth_entry.data[CONF_EMAIL]
            password = user_input[CONF_PASSWORD]
            try:
                tokens, profile = await _authenticate(self.hass, email, password)
            except DazeInvalidAuthError:
                errors["base"] = "invalid_auth"
            except (DazeCannotConnectError, aiohttp.ClientError, TimeoutError):
                errors["base"] = "cannot_connect"
            else:
                if profile["identityId"] != self._reauth_entry.unique_id:
                    errors["base"] = "wrong_account"
                else:
                    self.hass.config_entries.async_update_entry(
                        self._reauth_entry,
                        data={
                            **self._reauth_entry.data,
                            CONF_PASSWORD: password,
                            CONF_TOKEN: tokens.as_dict(),
                        },
                    )
                    await self.hass.config_entries.async_reload(self._reauth_entry.entry_id)
                    return self.async_abort(reason="reauth_successful")

        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=vol.Schema({vol.Required(CONF_PASSWORD): str}),
            errors=errors,
        )

    async def async_step_reauth_google(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Ask for a fresh refresh token when the stored one expired or was revoked."""
        errors: dict[str, str] = {}
        assert self._reauth_entry is not None
        if user_input is not None:
            refresh_token = _clean_token(user_input[CONF_REFRESH_TOKEN])
            try:
                _email, tokens, profile = await _authenticate_with_refresh_token(
                    self.hass, refresh_token
                )
            except DazeInvalidAuthError:
                errors["base"] = "invalid_token"
            except (DazeCannotConnectError, aiohttp.ClientError, TimeoutError):
                errors["base"] = "cannot_connect"
            except Exception:
                _LOGGER.exception("Unexpected error during Daze Google reauth")
                errors["base"] = "unknown"
            else:
                if profile["identityId"] != self._reauth_entry.unique_id:
                    errors["base"] = "wrong_account"
                else:
                    self.hass.config_entries.async_update_entry(
                        self._reauth_entry,
                        data={**self._reauth_entry.data, CONF_TOKEN: tokens.as_dict()},
                    )
                    await self.hass.config_entries.async_reload(self._reauth_entry.entry_id)
                    return self.async_abort(reason="reauth_successful")

        return self.async_show_form(
            step_id="reauth_google", data_schema=STEP_GOOGLE_DATA_SCHEMA, errors=errors
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> DazeOptionsFlow:
        return DazeOptionsFlow(config_entry)


class DazeOptionsFlow(OptionsFlow):
    def __init__(self, config_entry: ConfigEntry) -> None:
        self._config_entry = config_entry

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        if user_input is not None:
            return self.async_create_entry(data=user_input)

        current = self._config_entry.options.get(
            CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL.total_seconds()
        )
        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_SCAN_INTERVAL, default=current): vol.All(
                        vol.Coerce(int),
                        vol.Range(
                            min=MIN_SCAN_INTERVAL.total_seconds(),
                            max=MAX_SCAN_INTERVAL.total_seconds(),
                        ),
                    )
                }
            ),
        )
