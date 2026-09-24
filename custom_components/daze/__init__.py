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

PLATFORMS: list[Platform] = [Platform.BUTTON, Platform.SENSOR, Platform.SWITCH]


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

    coordinator = DazeCoordinator(
        hass,
        api,
        email=entry.data[CONF_EMAIL],
        identity_id=entry.unique_id,
        update_interval=_scan_interval(entry),
    )
    await coordinator.async_config_entry_first_refresh()

    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = coordinator
    entry.async_on_unload(entry.add_update_listener(_async_update_listener))

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


def _scan_interval(entry: ConfigEntry) -> timedelta:
    return timedelta(
        seconds=entry.options.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL.total_seconds())
    )


async def _async_update_listener(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Apply an entry update in place - never reload from here.

    This listener fires on *any* async_update_entry, including the token refresh
    persisted by _async_persist_tokens roughly every 55 min (3600s token lifetime
    minus TOKEN_REFRESH_LEEWAY_SECONDS). Reloading the entry there tore down and
    rebuilt every device/entity, so all sensors flickered to `unavailable` for
    about a second on each token refresh. The only user-configurable setting is
    the scan interval, which the coordinator can adopt live.
    """
    coordinator: DazeCoordinator = hass.data[DOMAIN][entry.entry_id]
    scan_interval = _scan_interval(entry)
    if coordinator.update_interval == scan_interval:
        return
    coordinator.update_interval = scan_interval
    # The setter alone doesn't touch the already-scheduled timer; refreshing now
    # reschedules the next poll with the new interval.
    await coordinator.async_request_refresh()


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        hass.data[DOMAIN].pop(entry.entry_id)
    return unload_ok
