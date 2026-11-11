"""Tests for the config loader and the shipped config.yaml."""

from pathlib import Path

from src.config import load_config

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


def test_shipped_config_declares_three_downloads_with_md5() -> None:
    files = load_config()["downloads"]["files"]

    assert [len(f["md5"]) for f in files] == [32, 32, 32]


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
