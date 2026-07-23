"""Constants for the Daze wallbox integration."""

from __future__ import annotations

from datetime import timedelta

DOMAIN = "daze"

# --- Cognito / OAuth ---
# TODO: find more generic region/user pool ID
COGNITO_REGION = "eu-central-1"
COGNITO_USER_POOL_ID = "eu-central-1_vXrLKLO3t"
COGNITO_CLIENT_ID = "4m0rp7oqarbrc3hn67ivvonba8"

# --- REST backend ---
WEBAPI_BASE_URL = "https://webapi.dazeservice.com"

# --- Config entry data/options keys ---
# CONF_EMAIL/CONF_PASSWORD are homeassistant.const's, reused as-is (not redefined here).
CONF_TOKEN = "token"

DEFAULT_SCAN_INTERVAL = timedelta(seconds=60)
MIN_SCAN_INTERVAL = timedelta(seconds=30)
MAX_SCAN_INTERVAL = timedelta(seconds=300)
CONF_SCAN_INTERVAL = "scan_interval"

# Number of concurrent /remoteInfo requests fired per poll cycle.
MAX_CONCURRENT_SOCKET_REQUESTS = 5

# Cognito access tokens are short-lived (observed: 3600s). Refresh proactively
# this many seconds before expiry rather than waiting for a 401.
TOKEN_REFRESH_LEEWAY_SECONDS = 300
