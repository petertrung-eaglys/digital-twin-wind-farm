"""Tests for feature engineering, splitting, metrics and per-turbine training."""

import numpy as np
import pandas as pd
import pytest
from rdflib import Graph

from src.graph_utils import get_model_target, get_sensors
from src.train import (
    add_direction_features,
    evaluate,
    feature_columns,
    parquet_path_of,
    split_masks,
    train_turbine,
)

RATED = 2050.0


def synthetic_turbine(n: int = 2000, seed: int = 0) -> pd.DataFrame:
    """A year of rows with a logistic power curve and a little noise."""
    rng = np.random.default_rng(seed)
    wind = rng.uniform(3, 20, n)
    power = RATED / (1 + np.exp(-(wind - 8.0))) + rng.normal(0, 10, n)
    return pd.DataFrame(
        {
            "timestamp": pd.date_range("2022-01-01", "2022-12-31", periods=n, tz="UTC"),
            "wind_speed": wind,
            "wind_direction": rng.uniform(0, 360, n),
            "air_density": rng.normal(1.225, 0.02, n),
            "power": power,
            "is_normal": True,
        }
    )


def test_feature_columns_follow_spec() -> None:
    inputs = ["ambient_temp", "wind_direction", "wind_speed"]

    assert feature_columns(inputs) == [
        "air_density",
        "wind_direction",
        "wind_dir_sin",
        "wind_dir_cos",
        "wind_speed",
    ]


def test_direction_features_on_unit_circle() -> None:
    frame = add_direction_features(pd.DataFrame({"wind_direction": [0.0, 90.0]}))

    assert frame[["wind_dir_sin", "wind_dir_cos"]].round(6).values.tolist() == [
        [0.0, 1.0],
        [1.0, 0.0],
    ]


def test_split_masks_use_train_end_and_normal_rows() -> None:
    frame = pd.DataFrame(
        {
            "timestamp": pd.to_datetime(
                ["2022-09-30 23:50", "2022-10-01 00:00", "2022-10-01 00:10"], utc=True
            ),
            "is_normal": [True, True, False],
        }
    )

    train, test = split_masks(frame, "2022-09-30 23:50")
    assert (train.tolist(), test.tolist()) == (
        [True, False, False],
        [False, True, False],
    )


def test_evaluate_normalises_by_rated_power() -> None:
    metrics = evaluate(pd.Series([100.0, 200.0]), np.array([110.0, 170.0]), 1000.0)

    assert metrics == {"mae_kw": 20.0, "nmae": 0.02}


def test_train_turbine_learns_power_curve() -> None:
    frame = synthetic_turbine()
    features = [
        "wind_speed",
        "air_density",
        "wind_direction",
        "wind_dir_sin",
        "wind_dir_cos",
    ]

    _, metrics, expected = train_turbine(
        frame, features, "power", RATED, "2022-09-30 23:50"
    )

    assert (metrics["nmae"] < 0.05, len(expected), metrics["n_test"] > 0) == (
        True,
        len(frame),
        True,
    )


def test_parquet_path_of_rejects_mixed_paths() -> None:
    sensors = pd.DataFrame({"parquet_path": ["a.parquet", "b.parquet"]})

    with pytest.raises(LookupError):
        parquet_path_of(sensors)


def test_graph_gives_target_and_parquet_path(graph: Graph) -> None:
    path = parquet_path_of(get_sensors(graph, "T01"))

    assert (get_model_target(graph, "T01"), str(path)) == (
        "power",
        "data/processed/scada_T01.parquet",
    )
