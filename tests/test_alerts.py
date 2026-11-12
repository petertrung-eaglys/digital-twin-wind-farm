"""Tests for residuals, period detection and lost energy."""

from datetime import UTC, datetime

import pandas as pd
import pytest
from rdflib import Graph

from src.alerts import find_periods, residual_fraction, run_ids
from src.graph_utils import add_alert, get_alerts, remove_alerts

RATED = 1000.0
CFG = {"window_samples": 2, "threshold_fraction": -0.05, "min_duration_samples": 2}


def frame_from_shortfalls(shortfalls: list[float]) -> pd.DataFrame:
    """Rows with expected 500 kW and power reduced by the given kW."""
    n = len(shortfalls)
    return pd.DataFrame(
        {
            "timestamp": pd.date_range("2022-10-01", periods=n, freq="10min", tz="UTC"),
            "expected_power": [500.0] * n,
            "power": [500.0 - s for s in shortfalls],
        }
    )


def periods_of(shortfalls: list[float]) -> pd.DataFrame:
    return find_periods(frame_from_shortfalls(shortfalls), RATED, CFG, 10)


def test_residual_fraction_relative_to_rated_power() -> None:
    frame = pd.DataFrame({"power": [400.0, 600.0], "expected_power": [500.0, 500.0]})

    assert residual_fraction(frame, RATED).tolist() == [-0.1, 0.1]


def test_run_ids_change_on_every_switch() -> None:
    assert run_ids(pd.Series([False, True, True, False, True])).tolist() == [
        1,
        2,
        2,
        3,
        4,
    ]


def test_no_periods_when_power_meets_expectation() -> None:
    periods = periods_of([0.0] * 6)

    assert (len(periods), list(periods.columns)) == (
        0,
        ["start", "end", "n_samples", "mean_residual_fraction", "lost_energy_mwh"],
    )


def test_period_needs_full_window_before_marking() -> None:
    # Rolling means (window 2): NaN, -0.1, -0.1, -0.1, -0.05, 0
    periods = periods_of([100.0, 100.0, 100.0, 100.0, 0.0, 0.0])

    assert periods[["start", "end", "n_samples"]].to_dict("records") == [
        {
            "start": pd.Timestamp("2022-10-01 00:10", tz="UTC"),
            "end": pd.Timestamp("2022-10-01 00:30", tz="UTC"),
            "n_samples": 3,
        }
    ]


def test_mean_residual_and_lost_energy_of_period() -> None:
    period = periods_of([100.0, 100.0, 100.0, 100.0, 0.0, 0.0]).iloc[0]

    # 3 marked samples x 100 kW x 1/6 h = 50 kWh = 0.05 MWh
    assert (period["mean_residual_fraction"], period["lost_energy_mwh"]) == (
        pytest.approx(-0.1),
        pytest.approx(0.05),
    )


def test_short_periods_are_dropped() -> None:
    # Rolling means: NaN, -0.1, -0.05, 0 -> one marked sample, below minimum 2
    assert len(periods_of([100.0, 100.0, 0.0, 0.0])) == 0


def test_separate_periods_are_kept_apart() -> None:
    shortfalls = [100.0] * 3 + [0.0] * 3 + [100.0] * 3

    assert periods_of(shortfalls)["n_samples"].tolist() == [2, 2]


def test_period_running_to_the_end_is_kept() -> None:
    periods = periods_of([0.0, 0.0, 100.0, 100.0, 100.0])

    assert periods["end"].tolist() == [pd.Timestamp("2022-10-01 00:40", tz="UTC")]


def test_remove_alerts_only_removes_that_turbine(graph: Graph) -> None:
    start, end = datetime(2022, 10, 1, tzinfo=UTC), datetime(2022, 10, 2, tzinfo=UTC)
    add_alert(graph, "T01", 1, start, end, -0.1, 1.0)
    add_alert(graph, "T01", 2, start, end, -0.1, 1.0)
    add_alert(graph, "T02", 1, start, end, -0.1, 1.0)

    removed = remove_alerts(graph, "T01")
    assert (removed, get_alerts(graph)["turbine_id"].tolist()) == (2, ["T02"])
