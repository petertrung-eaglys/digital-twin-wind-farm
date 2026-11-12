"""Add the is_normal flag and air_density to each turbine Parquet file.

The share of normal rows is printed, as spec 7.4 asks.
"""

import logging
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import pandas as pd  # noqa: E402

from src.config import load_config  # noqa: E402

logger = logging.getLogger(__name__)

DRY_AIR_GAS_CONSTANT = 287.05  # J/(kg K)
KELVIN_OFFSET = 273.15


def air_density(temp_c: pd.Series, pressure_pa: float) -> pd.Series:
    """Air density in kg/m3 from temperature via the ideal gas law."""
    return pressure_pa / (DRY_AIR_GAS_CONSTANT * (temp_c + KELVIN_OFFSET))


def normal_mask(frame: pd.DataFrame, cleaning: dict, required: list[str]) -> pd.Series:
    """True for rows that pass all cleaning rules of spec 7.4."""
    complete = frame[required].notna().all(axis=1)
    wind_ok = frame["wind_speed"].between(
        cleaning["min_wind_speed"], cleaning["max_wind_speed"]
    )
    power_ok = frame["power"] > cleaning["min_power_kw"]
    pitch_ok = (frame["wind_speed"] >= cleaning["rated_wind_speed"]) | (
        frame["pitch"] < cleaning["max_pitch_deg"]
    )
    return complete & wind_ok & power_ok & pitch_ok


def add_cleaning_columns(frame: pd.DataFrame, config: dict) -> pd.DataFrame:
    """Return the frame with is_normal and air_density columns added."""
    cleaning = config["cleaning"]
    required = [*config["model"]["inputs"], config["model"]["target"]]
    return frame.assign(
        is_normal=normal_mask(frame, cleaning, required),
        air_density=air_density(
            frame["ambient_temp"], cleaning["standard_pressure_pa"]
        ),
    )


def plot_power_curve(frame: pd.DataFrame, turbine_id: str, out: Path) -> None:
    """Save a wind speed vs power scatter with normal and excluded points."""
    fig, ax = plt.subplots(figsize=(8, 5))
    for normal, colour, label in [
        (False, "tab:red", "excluded"),
        (True, "tab:blue", "normal"),
    ]:
        part = frame[frame["is_normal"] == normal]
        ax.scatter(
            part["wind_speed"],
            part["power"],
            s=1,
            alpha=0.3,
            c=colour,
            label=f"{label} ({len(part)})",
        )
    ax.set(
        title=f"Power curve {turbine_id}",
        xlabel="Wind speed (m/s)",
        ylabel="Power (kW)",
    )
    ax.legend(markerscale=10)
    fig.savefig(out, dpi=100, bbox_inches="tight")
    plt.close(fig)


def main() -> None:
    """Clean every processed turbine file in place and save its power curve."""
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    config = load_config()
    models_dir = Path(config["paths"]["models"])
    models_dir.mkdir(parents=True, exist_ok=True)
    for path in sorted(Path(config["paths"]["processed"]).glob("scada_*.parquet")):
        frame = add_cleaning_columns(pd.read_parquet(path), config)
        frame.to_parquet(path, index=False)
        turbine_id = frame["turbine_id"].iloc[0]
        plot_power_curve(
            frame, turbine_id, models_dir / f"power_curve_{turbine_id}.png"
        )
        logger.info("Cleaned %s", path)
        print(f"{turbine_id}: {frame['is_normal'].mean():.1%} normal rows")


if __name__ == "__main__":
    main()
