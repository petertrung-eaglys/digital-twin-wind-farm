"""Tests for the SCADA export format helpers."""

from pathlib import Path

import pytest

from src.scada_format import (
    classify_file,
    format_turbine_id,
    group_by_turbine,
    group_files,
    header_line_index,
    parse_columns,
    read_head,
    turbine_data_files,
    turbine_id_from_filename,
)

SAMPLE = (
    "# Exported by Greenbyte\r\n"
    "#\r\n"
    "# Turbine: Kelmarsh 1\r\n"
    '# Date and time,Wind speed (m/s),"Wind speed, Minimum (m/s)",Power (kW)\r\n'
    "2022-01-01 00:00:00,5.1,4.2,300.0\r\n"
    "2022-01-01 00:10:00,5.3,4.4,320.0\r\n"
)


def test_classify_file_by_prefix() -> None:
    names = [
        "Turbine_Data_Kelmarsh_1_2022-01-01_-_2023-01-01_228.csv",
        "Status_Kelmarsh_1_2022-01-01_-_2023-01-01_228.csv",
        "readme.txt",
    ]

    assert [classify_file(n) for n in names] == ["turbine_data", "status", "other"]


def test_group_files_sorts_within_groups() -> None:
    names = [
        "Turbine_Data_Kelmarsh_2_x.csv",
        "Status_Kelmarsh_1_x.csv",
        "Turbine_Data_Kelmarsh_1_x.csv",
    ]

    assert group_files(names) == {
        "status": ["Status_Kelmarsh_1_x.csv"],
        "turbine_data": [
            "Turbine_Data_Kelmarsh_1_x.csv",
            "Turbine_Data_Kelmarsh_2_x.csv",
        ],
    }


def test_read_head_strips_crlf_and_bom(tmp_path: Path) -> None:
    path = tmp_path / "f.csv"
    path.write_bytes("﻿a,b\r\n1,2\r\n3,4\r\n".encode())

    assert read_head(path, 2) == ["a,b", "1,2"]


def test_header_line_index_is_last_comment_line(tmp_path: Path) -> None:
    lines = SAMPLE.splitlines()

    assert header_line_index(lines) == 3


def test_header_line_index_without_comments_is_minus_one() -> None:
    assert header_line_index(["2022-01-01,1"]) == -1


def test_parse_columns_strips_comment_and_respects_quotes() -> None:
    header = '# Date and time,Wind speed (m/s),"Wind speed, Minimum (m/s)",Power (kW)'

    assert parse_columns(header) == [
        "Date and time",
        "Wind speed (m/s)",
        "Wind speed, Minimum (m/s)",
        "Power (kW)",
    ]


def test_format_turbine_id_zero_pads() -> None:
    assert [format_turbine_id(n) for n in (1, 6, 12)] == ["T01", "T06", "T12"]


def test_turbine_id_from_filename() -> None:
    name = "Turbine_Data_Kelmarsh_3_2022-01-01_-_2023-01-01_230.csv"

    assert turbine_id_from_filename(name) == "T03"


def test_turbine_id_from_filename_rejects_unknown_name() -> None:
    with pytest.raises(ValueError, match="No turbine number"):
        turbine_id_from_filename("readme.csv")


def make_files(folder: Path, names: list[str]) -> list[Path]:
    folder.mkdir()
    for name in names:
        (folder / name).write_text("")
    return [folder / n for n in names]


def test_turbine_data_files_keeps_folder_order_and_skips_status(
    tmp_path: Path,
) -> None:
    late = make_files(tmp_path / "scada_2022", ["Turbine_Data_Kelmarsh_1_b.csv"])
    early = make_files(
        tmp_path / "scada_2021",
        ["Turbine_Data_Kelmarsh_1_a.csv", "Status_Kelmarsh_1_a.csv"],
    )

    assert turbine_data_files([early[0].parent, late[0].parent]) == [
        early[0],
        late[0],
    ]


def test_group_by_turbine_keeps_file_order_per_turbine() -> None:
    paths = [
        Path("2021/Turbine_Data_Kelmarsh_2_a.csv"),
        Path("2021/Turbine_Data_Kelmarsh_1_a.csv"),
        Path("2022/Turbine_Data_Kelmarsh_1_b.csv"),
    ]

    assert group_by_turbine(paths) == {
        "T01": [paths[1], paths[2]],
        "T02": [paths[0]],
    }
