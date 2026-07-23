"""The Daze wallbox integration."""

from __future__ import annotations

from datetime import timedelta

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_EMAIL, Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import DazeApiClient
from .auth import CognitoDirectAuthStrategy, DazeAuth, TokenSet
from .const import CONF_SCAN_INTERVAL, CONF_TOKEN, DEFAULT_SCAN_INTERVAL, DOMAIN
from .coordinator import DazeCoordinator

PLATFORMS: list[Platform] = [Platform.SENSOR]


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    session = async_get_clientsession(hass)
    tokens = TokenSet.from_dict(entry.data[CONF_TOKEN])

    async def _async_persist_tokens(new_tokens: TokenSet) -> None:
        hass.config_entries.async_update_entry(
            entry, data={**entry.data, CONF_TOKEN: new_tokens.as_dict()}
        )

    auth = DazeAuth(
        session,
        CognitoDirectAuthStrategy(),
        tokens=tokens,
        token_update_callback=_async_persist_tokens,
    )
    api = DazeApiClient(session, auth)

    scan_interval = entry.options.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL.total_seconds())
    coordinator = DazeCoordinator(
        hass,
        api,
        email=entry.data[CONF_EMAIL],
        identity_id=entry.unique_id,
        update_interval=timedelta(seconds=scan_interval),
    )
    await coordinator.async_config_entry_first_refresh()

    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = coordinator
    entry.async_on_unload(entry.add_update_listener(_async_update_listener))

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def _async_update_listener(hass: HomeAssistant, entry: ConfigEntry) -> None:
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        hass.data[DOMAIN].pop(entry.entry_id)
    return unload_ok
