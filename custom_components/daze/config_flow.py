"""Config flow for the Daze integration."""

from __future__ import annotations

import logging
from typing import Any

import aiohttp
import voluptuous as vol
from homeassistant.config_entries import ConfigEntry, ConfigFlow, ConfigFlowResult, OptionsFlow
from homeassistant.const import CONF_EMAIL, CONF_PASSWORD
from homeassistant.core import callback
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import DazeApiClient, DazeCannotConnectError
from .auth import CognitoDirectAuthStrategy, DazeAuth, DazeInvalidAuthError, TokenSet
from .const import (
    CONF_SCAN_INTERVAL,
    CONF_TOKEN,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
    MAX_SCAN_INTERVAL,
    MIN_SCAN_INTERVAL,
)

_LOGGER = logging.getLogger(__name__)

STEP_USER_DATA_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_EMAIL): str,
        vol.Required(CONF_PASSWORD): str,
    }
)


async def _authenticate(
    hass, email: str, password: str
) -> tuple[TokenSet, dict[str, Any]]:
    """Log in and fetch the profile in one go. Raises DazeInvalidAuthError/DazeCannotConnectError."""
    session = async_get_clientsession(hass)
    auth = DazeAuth(session, CognitoDirectAuthStrategy())
    tokens = await auth.async_login(email, password)
    api = DazeApiClient(session, auth)
    profile = await api.async_get_user_profile(email)
    if profile is None:
        raise DazeCannotConnectError("empty profile response")
    return tokens, profile


class DazeConfigFlow(ConfigFlow, domain=DOMAIN):
    VERSION = 1

    def __init__(self) -> None:
        self._reauth_entry: ConfigEntry | None = None

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            email = user_input[CONF_EMAIL]
            password = user_input[CONF_PASSWORD]
            try:
                tokens, profile = await _authenticate(self.hass, email, password)
            except DazeInvalidAuthError:
                errors["base"] = "invalid_auth"
            except (DazeCannotConnectError, aiohttp.ClientError):
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
            step_id="user", data_schema=STEP_USER_DATA_SCHEMA, errors=errors
        )

    async def async_step_reauth(self, entry_data: dict[str, Any]) -> ConfigFlowResult:
        self._reauth_entry = self.hass.config_entries.async_get_entry(self.context["entry_id"])
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        assert self._reauth_entry is not None
        if user_input is not None:
            email = self._reauth_entry.data[CONF_EMAIL]
            password = user_input[CONF_PASSWORD]
            try:
                tokens, profile = await _authenticate(self.hass, email, password)
            except DazeInvalidAuthError:
                errors["base"] = "invalid_auth"
            except (DazeCannotConnectError, aiohttp.ClientError):
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

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> "DazeOptionsFlow":
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
