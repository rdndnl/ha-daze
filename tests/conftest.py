from __future__ import annotations

import json
from pathlib import Path

import pytest

pytest_plugins = "pytest_homeassistant_custom_component"

FIXTURES_DIR = Path(__file__).parent / "fixtures"


def load_fixture(name: str) -> dict:
    with open(FIXTURES_DIR / name, encoding="utf-8") as f:
        return json.load(f)


@pytest.fixture
def user_profile_data() -> dict:
    return load_fixture("user_profile.json")["data"]


@pytest.fixture
def networks_data() -> list:
    return load_fixture("networks.json")["data"]


@pytest.fixture
def evses_data() -> list:
    return load_fixture("evses.json")["data"]


@pytest.fixture
def remote_info_data() -> dict:
    return load_fixture("remote_info.json")["data"]
