"""Detect underperformance periods from rolling residuals; store them as alerts.

Alert counts and lost energy are printed, as spec 7.8 asks.
"""

import logging

import pandas as pd

from src.config import load_config
from src.graph_utils import (
    add_alert,
    get_sensors,
    get_turbines,
    load_graph,
    remove_alerts,
    save_graph,
)
from src.train import parquet_path_of

logger = logging.getLogger(__name__)

MINUTES_PER_HOUR = 60
KW_PER_MW = 1000
PERIOD_COLUMNS = [
    "start",
    "end",
    "n_samples",
    "mean_residual_fraction",
    "lost_energy_mwh",
]


def residual_fraction(frame: pd.DataFrame, rated_power_kw: float) -> pd.Series:
    """(power - expected_power) / rated power."""
    return (frame["power"] - frame["expected_power"]) / rated_power_kw


def run_ids(marked: pd.Series) -> pd.Series:
    """Label each run of consecutive equal values with its own id."""
    return (marked != marked.shift()).cumsum()


def find_periods(
    normal: pd.DataFrame,
    rated_power_kw: float,
    alerts_cfg: dict,
    interval_minutes: float,
) -> pd.DataFrame:
    """Underperformance periods in a frame of normal rows, sorted by time."""
    data = normal.sort_values("timestamp").reset_index(drop=True)
    residual = residual_fraction(data, rated_power_kw)
    window = alerts_cfg["window_samples"]
    rolling = residual.rolling(window, min_periods=window).mean()
    marked = rolling < alerts_cfg["threshold_fraction"]
    hours_per_sample = interval_minutes / MINUTES_PER_HOUR
    periods = (
        data.assign(
            residual=residual,
            lost_kwh=(data["expected_power"] - data["power"]) * hours_per_sample,
            run=run_ids(marked),
        )[marked]
        .groupby("run")
        .agg(
            start=("timestamp", "min"),
            end=("timestamp", "max"),
            n_samples=("timestamp", "size"),
            mean_residual_fraction=("residual", "mean"),
            lost_energy_mwh=("lost_kwh", "sum"),
        )
    )
    long_enough = periods["n_samples"] >= alerts_cfg["min_duration_samples"]
    return (
        periods[long_enough]
        .assign(lost_energy_mwh=lambda p: p["lost_energy_mwh"] / KW_PER_MW)
        .reset_index(drop=True)
        .reindex(columns=PERIOD_COLUMNS)
    )


def main() -> None:
    """Find alert periods per turbine and write them into the graph."""
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    config = load_config()
    ontology = config["paths"]["ontology"]
    g = load_graph(ontology)
    totals = {}
    for turbine in get_turbines(g).itertuples():
        tid = turbine.turbine_id
        frame = pd.read_parquet(parquet_path_of(get_sensors(g, tid)))
        periods = find_periods(
            frame[frame["is_normal"]],
            turbine.rated_power_kw,
            config["alerts"],
            config["sampling"]["interval_minutes"],
        )
        remove_alerts(g, tid)
        for number, period in enumerate(periods.itertuples(), start=1):
            add_alert(
                g,
                tid,
                number,
                period.start,
                period.end,
                period.mean_residual_fraction,
                period.lost_energy_mwh,
            )
        totals[tid] = (len(periods), periods["lost_energy_mwh"].sum())
        print(f"{tid}: {totals[tid][0]} alerts, {totals[tid][1]:.1f} MWh lost")
    save_graph(g, ontology)
    logger.info("Updated %s", ontology)
    if all(count == 0 for count, _ in totals.values()):
        print(
            "No alerts for any turbine. Consider a looser alerts.threshold_fraction "
            "(e.g. -0.03) or a shorter alerts.min_duration_samples in config.yaml."
        )


if __name__ == "__main__":
    main()
