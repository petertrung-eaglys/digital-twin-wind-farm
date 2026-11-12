"""Tests for the config loader and the shipped config.yaml."""

from pathlib import Path

from src.config import load_config, scada_archives, scada_dirs

EXPECTED_SIGNAL_KEYS = {
    "wind_speed",
    "power",
    "wind_direction",
    "nacelle_direction",
    "ambient_temp",
    "pitch",
    "rotor_speed",
}


def test_load_config_reads_yaml(tmp_path: Path) -> None:
    path = tmp_path / "c.yaml"
    path.write_text("year: 2022\nalerts:\n  window_samples: 144\n", encoding="utf-8")

    assert load_config(path) == {"year": 2022, "alerts": {"window_samples": 144}}


def test_shipped_config_declares_all_seven_signals() -> None:
    assert set(load_config()["signals"]) == EXPECTED_SIGNAL_KEYS


def test_shipped_config_declares_eleven_downloads_with_md5() -> None:
    files = load_config()["downloads"]["files"]

    assert [len(f["md5"]) for f in files] == [32] * 11


def test_shipped_config_years_match_scada_archive_folders() -> None:
    config = load_config()

    assert [d.name for d in scada_dirs(config)] == [
        f"scada_{y}" for y in config["years"]
    ]


def test_shipped_config_trains_up_to_end_of_2021() -> None:
    assert load_config()["train_test_split"]["train_end"] == "2021-12-31 23:50"


def test_scada_archives_are_entries_with_extract_to() -> None:
    config = {
        "downloads": {
            "files": [
                {"name": "a.csv"},
                {"name": "b.zip", "extract_to": "scada_b"},
            ]
        }
    }

    assert scada_archives(config) == [{"name": "b.zip", "extract_to": "scada_b"}]


def test_shipped_config_has_all_sections() -> None:
    sections = {
        "paths",
        "downloads",
        "signals",
        "sampling",
        "cleaning",
        "train_test_split",
        "alerts",
    }

    assert sections <= set(load_config())


def test_shipped_config_names_the_timestamp_column() -> None:
    assert load_config()["scada"]["timestamp_column"] == "Date and time"


def test_shipped_config_uses_satellite_map() -> None:
    assert load_config()["dashboard"]["map_style"] == "satellite"
