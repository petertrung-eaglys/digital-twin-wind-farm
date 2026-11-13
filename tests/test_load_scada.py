"""Tests for the SCADA loader on a small synthetic Greenbyte-style file."""

from pathlib import Path

import pandas as pd
import pytest

from src.load_scada import (
    load_turbine,
    missing_percent,
    read_turbine_file,
    rows_per_year,
    tidy,
)

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
    return tidy(raw, "Date and time", SIGNALS, "T02", [2022])


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


HEADER = "# Exported by Greenbyte\r\n# Date and time,Wind speed (m/s),Power (kW)\r\n"
FILE_2021 = HEADER + (
    "2020-12-31 23:50:00,1.0,10.0\r\n"
    "2021-12-31 23:50:00,4.0,100.0\r\n"
    "2022-01-01 00:00:00,5.0,200.0\r\n"
)
FILE_2022 = HEADER + (
    "2022-01-01 00:00:00,9.9,999.0\r\n"
    "2022-01-01 00:10:00,5.3,300.0\r\n"
    "2023-01-01 00:00:00,6.0,400.0\r\n"
)
MULTI_YEAR_CONFIG = {
    "scada": {"timestamp_column": "Date and time"},
    "signals": SIGNALS,
    "years": [2021, 2022],
}


@pytest.fixture
def yearly_files(tmp_path: Path) -> list[Path]:
    paths = []
    for year, text in [(2021, FILE_2021), (2022, FILE_2022)]:
        folder = tmp_path / f"scada_{year}"
        folder.mkdir()
        path = folder / f"Turbine_Data_Kelmarsh_1_{year}.csv"
        path.write_text(text, encoding="utf-8")
        paths.append(path)
    return paths


def test_load_turbine_combines_years_and_drops_other_years(
    yearly_files: list[Path],
) -> None:
    frame = load_turbine("T01", yearly_files, MULTI_YEAR_CONFIG)

    assert list(frame["timestamp"].astype(str)) == [
        "2021-12-31 23:50:00+00:00",
        "2022-01-01 00:00:00+00:00",
        "2022-01-01 00:10:00+00:00",
    ]


def test_load_turbine_keeps_first_file_row_at_year_boundary(
    yearly_files: list[Path],
) -> None:
    frame = load_turbine("T01", yearly_files, MULTI_YEAR_CONFIG)
    boundary = frame["timestamp"] == pd.Timestamp("2022-01-01 00:00", tz="UTC")

    assert frame.loc[boundary, "power"].tolist() == [200.0]


def test_load_turbine_sets_turbine_id(yearly_files: list[Path]) -> None:
    frame = load_turbine("T01", yearly_files, MULTI_YEAR_CONFIG)

    assert set(frame["turbine_id"]) == {"T01"}


def test_rows_per_year_counts_by_timestamp_year(yearly_files: list[Path]) -> None:
    frame = load_turbine("T01", yearly_files, MULTI_YEAR_CONFIG)

    assert rows_per_year(frame) == {2021: 1, 2022: 2}


def test_tidy_prefers_complete_row_over_earlier_nan_copy() -> None:
    raw = pd.DataFrame(
        {
            "Date and time": ["2023-01-01 00:00:00"] * 3,
            "Wind speed (m/s)": [None, 5.0, 6.0],
            "Power (kW)": [None, None, 300.0],
        }
    )

    frame = tidy(raw, "Date and time", SIGNALS, "T01", [2023])

    assert frame[["wind_speed", "power"]].values.tolist() == [[6.0, 300.0]]
