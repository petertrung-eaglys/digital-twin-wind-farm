"""Load the raw SCADA turbine files of all years into one Parquet per turbine.

Row counts and missing percentages are printed, as spec 7.3 asks.
"""

import logging
from pathlib import Path

import pandas as pd

from src.config import load_config, scada_dirs
from src.scada_format import (
    group_by_turbine,
    header_line_index,
    parse_columns,
    read_head,
    turbine_data_files,
)

logger = logging.getLogger(__name__)

HEADER_SEARCH_LINES = 50


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
    years: list[int],
) -> pd.DataFrame:
    """Rename to config keys, parse UTC timestamps, keep years, dedupe.

    Duplicate timestamps (year-file boundaries, repeated rows in the 2023 and
    2024 exports) keep the row with the most non-missing signals; ties keep
    the first row in file order.
    """
    renamed = raw.rename(columns={v: k for k, v in signals.items()})
    timestamp = pd.to_datetime(raw[timestamp_column], utc=True)
    frame = renamed.assign(timestamp=timestamp, turbine_id=turbine_id)[
        ["timestamp", "turbine_id", *signals]
    ]
    in_years = frame[frame["timestamp"].dt.year.isin(years)]
    present = in_years[list(signals)].notna().sum(axis=1).rename("present")
    return (
        in_years.join(present)
        .sort_values(["timestamp", "present"], ascending=[True, False], kind="stable")
        .drop_duplicates(subset="timestamp")
        .drop(columns="present")
        .reset_index(drop=True)
    )


def missing_percent(frame: pd.DataFrame) -> pd.Series:
    """Percentage of missing values per column, rounded to 0.1."""
    return (frame.isna().mean() * 100).round(1)


def rows_per_year(frame: pd.DataFrame) -> dict[int, int]:
    """Number of rows per calendar year of the timestamp."""
    return frame["timestamp"].dt.year.value_counts().sort_index().to_dict()


def load_turbine(turbine_id: str, paths: list[Path], config: dict) -> pd.DataFrame:
    """Read, concatenate in the given order and tidy all files of one turbine."""
    timestamp_column = config["scada"]["timestamp_column"]
    signals = config["signals"]
    wanted = [timestamp_column, *signals.values()]
    raw = pd.concat([read_turbine_file(p, wanted) for p in paths], ignore_index=True)
    return tidy(raw, timestamp_column, signals, turbine_id, config["years"])


def main() -> None:
    """Write data/processed/scada_<turbine_id>.parquet for every turbine."""
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    config = load_config()
    out_dir = Path(config["paths"]["processed"])
    out_dir.mkdir(parents=True, exist_ok=True)
    files = group_by_turbine(turbine_data_files(scada_dirs(config)))
    for turbine_id, paths in files.items():
        logger.info("Loading %d files for %s", len(paths), turbine_id)
        frame = load_turbine(turbine_id, paths, config)
        out = out_dir / f"scada_{turbine_id}.parquet"
        frame.to_parquet(out, index=False)
        logger.info("Wrote %s", out)
        print(f"\n{turbine_id}: {len(frame)} rows")
        print(f"Rows per year: {rows_per_year(frame)}")
        print(f"Missing %: {missing_percent(frame).to_dict()}")


if __name__ == "__main__":
    main()
