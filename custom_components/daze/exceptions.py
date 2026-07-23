"""Shared exception hierarchy for the Daze integration.

Defined once here and imported by both auth.py and api.py so a DazeCannotConnectError
raised during login (auth.py) and one raised during a REST call (api.py) are the same
type - config_flow.py only needs to catch one thing either way.
"""

from __future__ import annotations


class DazeError(Exception):
    """Base class for all Daze integration errors."""


class DazeAuthError(DazeError):
    """Base class for auth failures."""


class DazeInvalidAuthError(DazeAuthError):
    """Credentials rejected (wrong password, disabled flow, etc.)."""


class DazeCannotConnectError(DazeError):
    """Network/timeout/backend-unavailable error (auth or REST layer)."""
