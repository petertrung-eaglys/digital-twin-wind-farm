"""Train one LightGBM power model per turbine, discovered through the graph."""

import json
import logging
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import pandas as pd
from lightgbm import LGBMRegressor
from sklearn.metrics import mean_absolute_error

from src.config import load_config
from src.graph_utils import (
    add_model,
    get_model_inputs,
    get_model_target,
    get_sensors,
    get_turbines,
    load_graph,
    parquet_path_of,
    save_graph,
)

logger = logging.getLogger(__name__)

N_ESTIMATORS = 300
NMAE_LIMIT = 0.05

# model input signal -> feature columns derived from it (spec 7.7)
FEATURES_FROM_SIGNAL = {
    "wind_speed": ["wind_speed"],
    "ambient_temp": ["air_density"],
    "wind_direction": ["wind_direction", "wind_dir_sin", "wind_dir_cos"],
}


def feature_columns(inputs: list[str]) -> list[str]:
    """Feature columns derived from the model's input signals."""
    return [col for key in inputs for col in FEATURES_FROM_SIGNAL[key]]


def add_direction_features(frame: pd.DataFrame) -> pd.DataFrame:
    """Add sin and cos of the wind direction (degrees)."""
    radians = np.deg2rad(frame["wind_direction"])
    return frame.assign(wind_dir_sin=np.sin(radians), wind_dir_cos=np.cos(radians))


def split_masks(frame: pd.DataFrame, train_end: str) -> tuple[pd.Series, pd.Series]:
    """Train and test masks: normal rows up to train_end, and after it."""
    end = pd.Timestamp(train_end, tz="UTC")
    before = frame["timestamp"] <= end
    return frame["is_normal"] & before, frame["is_normal"] & ~before


def evaluate(y_true: pd.Series, y_pred: np.ndarray, rated_power_kw: float) -> dict:
    """MAE in kW and MAE normalised by rated power."""
    mae = float(mean_absolute_error(y_true, y_pred))
    return {"mae_kw": mae, "nmae": mae / rated_power_kw}


def train_turbine(
    frame: pd.DataFrame,
    features: list[str],
    target: str,
    rated_power_kw: float,
    train_end: str,
) -> tuple[LGBMRegressor, dict, np.ndarray]:
    """Fit on train rows, score on test rows, predict for all rows."""
    data = add_direction_features(frame)
    train, test = split_masks(data, train_end)
    model = LGBMRegressor(n_estimators=N_ESTIMATORS, verbose=-1)
    model.fit(data.loc[train, features], data.loc[train, target])
    metrics = evaluate(
        data.loc[test, target], model.predict(data.loc[test, features]), rated_power_kw
    )
    metrics |= {"n_train": int(train.sum()), "n_test": int(test.sum())}
    return model, metrics, model.predict(data[features])


def main() -> None:
    """Train, save and register a power model for every turbine in the graph."""
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    config = load_config()
    ontology = config["paths"]["ontology"]
    models_dir = Path(config["paths"]["models"])
    models_dir.mkdir(parents=True, exist_ok=True)
    g = load_graph(ontology)
    all_metrics = {}
    for turbine in get_turbines(g).itertuples():
        tid = turbine.turbine_id
        inputs = get_model_inputs(g, tid)
        target = get_model_target(g, tid)
        path = parquet_path_of(get_sensors(g, tid))
        frame = pd.read_parquet(path)
        model, metrics, expected = train_turbine(
            frame,
            feature_columns(inputs),
            target,
            turbine.rated_power_kw,
            config["train_test_split"]["train_end"],
        )
        model.booster_.save_model(models_dir / f"power_{tid}.txt")
        frame.assign(expected_power=expected).to_parquet(path, index=False)
        add_model(g, tid, inputs, target, metrics, datetime.now(UTC))
        all_metrics[tid] = metrics
        logger.info(
            "%s: MAE %.1f kW, nMAE %.4f", tid, metrics["mae_kw"], metrics["nmae"]
        )
        if metrics["nmae"] >= NMAE_LIMIT:
            logger.warning(
                "%s: nMAE %.4f is not below %.2f", tid, metrics["nmae"], NMAE_LIMIT
            )
    save_graph(g, ontology)
    (models_dir / "metrics.json").write_text(json.dumps(all_metrics, indent=2))
    logger.info("Wrote %s and updated %s", models_dir / "metrics.json", ontology)


if __name__ == "__main__":
    main()
