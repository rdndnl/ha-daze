Home Assistant custom integration for Daze EV charging products (Dazebox)
=========================================================================

[![hacs_badge](https://img.shields.io/badge/HACS-Custom-orange.svg)](https://github.com/hacs/integration)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

Home Assistant custom integration that exposes sensor data from a [Daze](https://www.dazeservice.com/) EV wallbox charger,
read from the same backend used by the official [webportal.dazeservice.com](https://webportal.dazeservice.com/) web app.

> **Unofficial project.** This integration is not affiliated with, endorsed by, or supported by Daze.
> It was built by reverse-engineering the public web portal's network traffic, since Daze does not publish
> a public API. It may break without notice if Daze changes their backend.

## Features

Current release contains **read-only sensors**, no charge control (start/stop, eco mode) - that may come in a future release.

Per charging socket:

- Power (W) and current session energy (kWh)
- Charging current and AC voltage per phase (L1/L2/L3, when the installation is three-phase)
- Board and case temperature
- Fan status
- Raw status / EVSE state codes (not yet mapped to human-readable labels - see [Limitations](#limitations))

Per wallbox (diagnostic):

- Wi-Fi SSID, software/firmware version
- Grid current per phase

Per site ("network" in Daze's terminology):

- Energy tariff and currency

## Requirements

- Home Assistant 2024.1.0 or newer
- A Daze account (the same email/password you use with mobile App or at [webportal.dazeservice.com](https://webportal.dazeservice.com/))

## Installation

### Via HACS (custom repository)

This integration is not in the default HACS store. Add it as a custom repository:

1. HACS → the `⋮` menu (top right) → **Custom repositories**
2. Repository: `https://github.com/rdndnl/ha-daze`, Category: **Integration**
3. Find "Daze" in HACS and install it
4. Restart Home Assistant

### Manual

Copy `custom_components/daze` into your Home Assistant `config/custom_components/` directory,
then restart Home Assistant.

## Configuration

Settings → Devices & Services → **Add Integration** → search for **Daze** → enter your Daze account email and password.

Polling interval (default 60s) can be adjusted afterwards from the integration's **Configure** options.

## Limitations

- No charge start/stop or eco mode control yet (planned for a later release).
- `status`/`evse_state` sensors expose raw vendor integer codes: the mapping to human-readable states (charging, available, error, ...).
  Contributions with observed value/state pairs are welcome.
- Authenticates against the same AWS Cognito app client the web portal uses, via direct `USER_PASSWORD_AUTH` (no browser/webview involved).
  If Daze disables that auth flow this integration will need rework.

## Development

### Setup

Requires Python 3.14+ and [`uv`](https://docs.astral.sh/uv/).

```bash
uv sync
```

This installs the dev/test tooling declared in `pyproject.toml`'s `dev` dependency group
(Home Assistant core, pytest, and the libraries used by `scripts/auth_spike.py`). The
integration itself has no runtime dependencies beyond what Home Assistant already
provides - see `custom_components/daze/manifest.json`.

### Running the tests

```bash
uv run python -m pytest tests/ -q
```

Use `python -m pytest`, not bare `uv run pytest` - the latter doesn't add the repo
root to `sys.path`, so the `custom_components` package won't be importable.

Tests run against fixture payloads captured from real HAR sessions
(`tests/fixtures/*.json`) plus Home Assistant's own test harness
(`pytest-homeassistant-custom-component`) - no live Daze account or network access is
needed to run them.

### Testing against a real Home Assistant instance

Symlink the integration into your HA config and restart HA:

```bash
ln -s "$(pwd)/custom_components/daze" /path/to/homeassistant/config/custom_components/daze
```

Then add it from Settings → Devices & Services as usual.

### `scripts/auth_spike.py`

A standalone script (not part of the shipped integration) used to verify which Cognito
auth flow the backend accepts, without going through Home Assistant. Useful if Daze
ever changes their auth setup and `custom_components/daze/auth.py` needs revisiting:

```bash
DAZE_EMAIL="you@example.com" DAZE_PASSWORD="..." uv run python scripts/auth_spike.py
```

## Contributing

Issues and PRs are welcome at [github.com/rdndnl/ha-daze](https://github.com/rdndnl/ha-daze/issues).

## License

[MIT](LICENSE)
