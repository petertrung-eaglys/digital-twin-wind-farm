"""Load the raw SCADA turbine files into one Parquet file per turbine.

Row counts and missing percentages are printed, as spec 7.3 asks.
"""

import logging
from pathlib import Path

import pandas as pd

from src.config import load_config
from src.scada_format import (
    header_line_index,
    parse_columns,
    read_head,
    turbine_id_from_filename,
)

logger = logging.getLogger(__name__)

HEADER_SEARCH_LINES = 50
TURBINE_FILE_GLOB = "Turbine_Data_*.csv"


def read_turbine_file(path: Path, columns_wanted: list[str]) -> pd.DataFrame:
    """Read the wanted columns of one raw turbine file, skipping metadata."""
    lines = read_head(path, HEADER_SEARCH_LINES)
    index = header_line_index(lines)
    columns = parse_columns(lines[index])
    missing = set(columns_wanted) - set(columns)
    if missing:
        raise KeyError(f"{path.name} lacks columns: {sorted(missing)}")
    return pd.read_csv(
        path,
        skiprows=index + 1,
        header=None,
        names=columns,
        usecols=columns_wanted,
        encoding="utf-8-sig",
    )


def tidy(
    raw: pd.DataFrame,
    timestamp_column: str,
    signals: dict[str, str],
    turbine_id: str,
    year: int,
) -> pd.DataFrame:
    """Rename to config keys, parse UTC timestamps, keep one year, dedupe."""
    renamed = raw.rename(columns={v: k for k, v in signals.items()})
    timestamp = pd.to_datetime(raw[timestamp_column], utc=True)
    frame = renamed.assign(timestamp=timestamp, turbine_id=turbine_id)[
        ["timestamp", "turbine_id", *signals]
    ]
    in_year = frame["timestamp"].dt.year == year
    return (
        frame[in_year]
        .drop_duplicates(subset="timestamp")
        .sort_values("timestamp")
        .reset_index(drop=True)
    )


def missing_percent(frame: pd.DataFrame) -> pd.Series:
    """Percentage of missing values per column, rounded to 0.1."""
    return (frame.isna().mean() * 100).round(1)


def load_turbine(path: Path, config: dict) -> pd.DataFrame:
    """Read and tidy one turbine file according to the config."""
    timestamp_column = config["scada"]["timestamp_column"]
    signals = config["signals"]
    raw = read_turbine_file(path, [timestamp_column, *signals.values()])
    return tidy(
        raw,
        timestamp_column,
        signals,
        turbine_id_from_filename(path.name),
        config["year"],
    )


def main() -> None:
    """Write data/processed/scada_<turbine_id>.parquet for every turbine file."""
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    config = load_config()
    scada_dir = Path(config["paths"]["raw"]) / config["downloads"]["scada_dir"]
    out_dir = Path(config["paths"]["processed"])
    out_dir.mkdir(parents=True, exist_ok=True)
    for path in sorted(scada_dir.glob(TURBINE_FILE_GLOB)):
        frame = load_turbine(path, config)
        turbine_id = frame["turbine_id"].iloc[0]
        out = out_dir / f"scada_{turbine_id}.parquet"
        frame.to_parquet(out, index=False)
        logger.info("Wrote %s", out)
        print(f"\n{turbine_id}: {len(frame)} rows")
        print(f"Missing %: {missing_percent(frame).to_dict()}")


if __name__ == "__main__":
    main()
