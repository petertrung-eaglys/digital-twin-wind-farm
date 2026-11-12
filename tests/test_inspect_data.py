"""Tests for the raw-file inspection helpers."""

from src.inspect_data import missing_columns


def test_missing_columns_lists_absent_wanted_columns_in_order() -> None:
    columns = ["Date and time", "Power (kW)"]

    assert missing_columns(columns, ["Wind speed (m/s)", "Power (kW)", "Pitch"]) == [
        "Wind speed (m/s)",
        "Pitch",
    ]
