"""Tests for the SCADA loader on a small synthetic Greenbyte-style file."""

from pathlib import Path

import pandas as pd
import pytest

from src.load_scada import missing_percent, read_turbine_file, tidy

SIGNALS = {"wind_speed": "Wind speed (m/s)", "power": "Power (kW)"}
SAMPLE = (
    "# Exported by Greenbyte\r\n"
    "# Time zone: UTC\r\n"
    '# Date and time,Wind speed (m/s),"Wind speed, Minimum (m/s)",Power (kW)\r\n'
    "2021-12-31 23:50:00,4.0,3.0,100.0\r\n"
    "2022-01-01 00:10:00,5.3,4.4,NaN\r\n"
    "2022-01-01 00:00:00,5.1,4.2,300.0\r\n"
    "2022-01-01 00:00:00,5.1,4.2,300.0\r\n"
    "2023-01-01 00:00:00,6.0,5.0,400.0\r\n"
)


@pytest.fixture
def raw_file(tmp_path: Path) -> Path:
    path = tmp_path / "Turbine_Data_Kelmarsh_2_x.csv"
    path.write_text(SAMPLE, encoding="utf-8")
    return path


def test_read_turbine_file_reads_only_wanted_columns(raw_file: Path) -> None:
    raw = read_turbine_file(raw_file, ["Date and time", *SIGNALS.values()])

    assert (list(raw.columns), len(raw)) == (
        ["Date and time", "Wind speed (m/s)", "Power (kW)"],
        5,
    )


def test_read_turbine_file_reports_missing_columns(raw_file: Path) -> None:
    with pytest.raises(KeyError, match="Rotor speed"):
        read_turbine_file(raw_file, ["Date and time", "Rotor speed (RPM)"])


def tidy_sample(raw_file: Path) -> pd.DataFrame:
    raw = read_turbine_file(raw_file, ["Date and time", *SIGNALS.values()])
    return tidy(raw, "Date and time", SIGNALS, "T02", 2022)


def test_tidy_renames_to_config_keys(raw_file: Path) -> None:
    assert list(tidy_sample(raw_file).columns) == [
        "timestamp",
        "turbine_id",
        "wind_speed",
        "power",
    ]


def test_tidy_keeps_year_dedupes_and_sorts_utc(raw_file: Path) -> None:
    timestamps = tidy_sample(raw_file)["timestamp"]

    assert list(timestamps) == [
        pd.Timestamp("2022-01-01 00:00", tz="UTC"),
        pd.Timestamp("2022-01-01 00:10", tz="UTC"),
    ]


def test_tidy_parses_nan_as_missing(raw_file: Path) -> None:
    assert tidy_sample(raw_file)["power"].isna().tolist() == [False, True]


def test_missing_percent_per_column() -> None:
    frame = pd.DataFrame({"a": [1.0, None, None, 4.0], "b": [1.0, 2.0, 3.0, 4.0]})

    assert missing_percent(frame).to_dict() == {"a": 50.0, "b": 0.0}
