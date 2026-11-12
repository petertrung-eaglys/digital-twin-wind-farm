"""Tests for the cleaning rules, air density and the power curve plot."""

from pathlib import Path

import pandas as pd
import pytest

from src.clean import add_cleaning_columns, air_density, normal_mask, plot_power_curve

CLEANING = {
    "min_wind_speed": 3.0,
    "max_wind_speed": 25.0,
    "max_pitch_deg": 5.0,
    "min_power_kw": 0.0,
    "rated_wind_speed": 12.0,
    "standard_pressure_pa": 101325.0,
}
CONFIG = {
    "cleaning": CLEANING,
    "model": {
        "inputs": ["wind_speed", "wind_direction", "ambient_temp"],
        "target": "power",
    },
}
REQUIRED = ["wind_speed", "wind_direction", "ambient_temp", "power"]


def row(**overrides: float) -> dict:
    """A normal row, with selected values overridden."""
    base = {
        "wind_speed": 8.0,
        "wind_direction": 200.0,
        "ambient_temp": 10.0,
        "power": 1000.0,
        "pitch": 0.0,
    }
    return {**base, **overrides}


def mask_of(*rows: dict) -> list[bool]:
    return normal_mask(pd.DataFrame(rows), CLEANING, REQUIRED).tolist()


def test_typical_operating_row_is_normal() -> None:
    assert mask_of(row()) == [True]


def test_missing_input_or_target_is_not_normal() -> None:
    assert mask_of(row(ambient_temp=float("nan")), row(power=float("nan"))) == [
        False,
        False,
    ]


def test_wind_speed_outside_range_is_not_normal() -> None:
    assert mask_of(row(wind_speed=2.9), row(wind_speed=25.1), row(wind_speed=3.0)) == [
        False,
        False,
        True,
    ]


def test_non_positive_power_is_not_normal() -> None:
    assert mask_of(row(power=0.0), row(power=-5.0)) == [False, False]


def test_high_pitch_below_rated_wind_is_not_normal() -> None:
    assert mask_of(row(wind_speed=8.0, pitch=10.0)) == [False]


def test_high_pitch_above_rated_wind_is_normal() -> None:
    assert mask_of(row(wind_speed=15.0, pitch=10.0)) == [True]


def test_air_density_at_standard_conditions() -> None:
    assert air_density(pd.Series([15.0]), 101325.0)[0] == pytest.approx(1.225, abs=1e-3)


def test_add_cleaning_columns_adds_both_columns() -> None:
    frame = add_cleaning_columns(pd.DataFrame([row()]), CONFIG)

    assert {"is_normal", "air_density"} <= set(frame.columns)


def test_plot_power_curve_writes_png(tmp_path: Path) -> None:
    frame = add_cleaning_columns(pd.DataFrame([row(), row(power=0.0)]), CONFIG)
    out = tmp_path / "curve.png"

    plot_power_curve(frame, "T01", out)

    assert out.read_bytes()[:4] == b"\x89PNG"
