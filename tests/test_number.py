from __future__ import annotations

import pytest

from custom_components.daze.number import current_ma_to_power_kw, power_kw_to_current_ma


# Pairs observed in the vendor app on a three-phase DT01.
@pytest.mark.parametrize(
    ("power_kw", "current_ma"),
    [(4.5, 6521), (5.0, 7246), (11.1, 16086)],
)
def test_kw_ma_conversion_matches_the_app(power_kw, current_ma):
    assert power_kw_to_current_ma(power_kw, 3) == current_ma
    assert current_ma_to_power_kw(current_ma, 3) == power_kw


def test_single_phase_conversion():
    assert power_kw_to_current_ma(1.5, 1) == 6521
    assert current_ma_to_power_kw(6521, 1) == 1.5
