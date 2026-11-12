"""Tests for the dashboard helpers (status, windows, KPIs, replay, DuckDB)."""

from pathlib import Path

import pandas as pd
import pytest

from src import dashboard as db

T0 = pd.Timestamp("2022-10-01 00:00", tz="UTC")


def ts(minutes: int) -> pd.Timestamp:
    return T0 + pd.Timedelta(minutes=minutes)


def frame(n: int = 4, normal: bool = True) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "timestamp": [ts(10 * i) for i in range(n)],
            "turbine_id": "T01",
            "wind_speed": [8.0] * n,
            "power": [900.0] * n,
            "expected_power": [1000.0] * n,
            "is_normal": [normal] * n,
        }
    )


ALERTS = pd.DataFrame({"start": [ts(10)], "end": [ts(20)]})
NO_ALERTS = ALERTS.iloc[0:0]


def test_row_at_takes_latest_row_not_after_ts() -> None:
    assert db.row_at(frame(), ts(25))["timestamp"] == ts(20)


def test_row_at_before_data_is_none() -> None:
    assert db.row_at(frame(), ts(-10)) is None


def test_in_alert_includes_period_bounds() -> None:
    assert [db.in_alert(ts(m), ALERTS) for m in (0, 10, 20, 30)] == [
        False,
        True,
        True,
        False,
    ]


def test_status_red_inside_alert_even_if_not_normal() -> None:
    row = frame(normal=False).iloc[1]

    assert db.turbine_status(row, ts(10), ALERTS) == "alert"


def test_status_green_or_amber_outside_alerts() -> None:
    statuses = [
        db.turbine_status(frame(normal=True).iloc[0], ts(0), NO_ALERTS),
        db.turbine_status(frame(normal=False).iloc[0], ts(0), NO_ALERTS),
        db.turbine_status(None, ts(0), NO_ALERTS),
    ]

    assert statuses == ["normal", "not normal", "not normal"]


def test_window_keeps_last_days_up_to_end() -> None:
    rows = db.window(frame(), ts(30), days=0)

    assert len(rows) == 0 and len(db.window(frame(), ts(20), days=1)) == 3


def test_alerts_overlapping_window() -> None:
    assert [
        len(db.alerts_overlapping(ALERTS, ts(a), ts(b)))
        for a, b in [(0, 5), (0, 10), (15, 40), (25, 40)]
    ] == [0, 1, 1, 0]


def test_kpis_residual_fraction_of_rated_power() -> None:
    values = db.kpis(frame().iloc[0], 2000.0)

    assert values == {
        "power": 900.0,
        "expected_power": 1000.0,
        "residual_fraction": -0.05,
        "wind_speed": 8.0,
    }


def test_kpis_without_row_are_missing() -> None:
    assert set(db.kpis(None, 2000.0).values()) == {None}


def test_advance_moves_by_samples_and_stops_at_end() -> None:
    assert [db.advance(ts(0), 6, 10, ts(120)), db.advance(ts(100), 6, 10, ts(120))] == [
        (ts(60), True),
        (ts(120), False),
    ]


def test_load_series_reads_parquet_in_utc(tmp_path: Path) -> None:
    paths = []
    for tid in ("T01", "T02"):
        path = tmp_path / f"scada_{tid}.parquet"
        frame().assign(turbine_id=tid).to_parquet(path, index=False)
        paths.append(path)

    series = db.load_series(paths)
    assert (
        len(series),
        series["timestamp"].iloc[0],
        series["turbine_id"].unique().tolist(),
    ) == (
        8,
        T0,
        ["T01", "T02"],
    )


@pytest.mark.parametrize("status", ["normal", "not normal", "alert"])
def test_every_status_has_a_colour(status: str) -> None:
    assert db.STATUS_COLOURS[status].startswith("#")


def test_map_center_is_mean_of_turbine_coordinates() -> None:
    turbines = pd.DataFrame({"lat": [52.40, 52.42], "long": [-0.95, -0.93]})

    center = db.map_center(turbines)
    assert (center["lat"], center["lon"]) == (
        pytest.approx(52.41),
        pytest.approx(-0.94),
    )


def test_active_alerts_returns_iris_containing_ts() -> None:
    alerts = pd.DataFrame(
        {"alert": ["kt:A1", "kt:A2"], "start": [ts(0), ts(30)], "end": [ts(20), ts(40)]}
    )

    assert [db.active_alerts(alerts, ts(m)) for m in (10, 25, 30)] == [
        {"kt:A1"},
        set(),
        {"kt:A2"},
    ]


def test_sample_rows_keeps_small_frames_whole() -> None:
    frame = pd.DataFrame({"x": range(5)})

    assert db.sample_rows(frame, 10).equals(frame)


def test_sample_rows_caps_reproducibly_in_original_order() -> None:
    frame = pd.DataFrame({"x": range(1000)})
    first = db.sample_rows(frame, 100)

    assert (
        len(first),
        first.index.is_monotonic_increasing,
        first.equals(db.sample_rows(frame, 100)),
    ) == (100, True, True)


def test_clamp_limits_to_range() -> None:
    assert [db.clamp(ts(m), ts(0), ts(30)) for m in (-10, 10, 40)] == [
        ts(0),
        ts(10),
        ts(30),
    ]


def test_replay_start_is_first_sample_after_train_end() -> None:
    first = pd.Timestamp("2016-01-03", tz="UTC")
    last = pd.Timestamp("2024-12-31 23:50", tz="UTC")

    assert [
        db.replay_start(first, last, "2021-12-31 23:50", 10),
        db.replay_start(first, last, "2030-01-01", 10),
    ] == [pd.Timestamp("2022-01-01", tz="UTC"), last]


def test_year_span_covers_whole_years() -> None:
    start, end = db.year_span(2022, 2023)

    assert (start, end.strftime("%Y-%m-%d %H:%M:%S"), end.year) == (
        pd.Timestamp("2022-01-01", tz="UTC"),
        "2023-12-31 23:59:59",
        2023,
    )


def test_rows_between_includes_bounds() -> None:
    assert db.rows_between(frame(), ts(10), ts(20))["timestamp"].tolist() == [
        ts(10),
        ts(20),
    ]


def two_years() -> pd.DataFrame:
    """T01 in Dec 2022 and Jan 2023 (2 rows each, one not normal in 2023)."""
    times = pd.to_datetime(
        ["2022-12-01", "2022-12-02", "2023-01-01", "2023-01-02"], utc=True
    )
    return pd.DataFrame(
        {
            "timestamp": times,
            "turbine_id": "T01",
            "wind_speed": 8.0,
            "power": [900.0, 700.0, 1000.0, 0.0],
            "expected_power": [1000.0, 1000.0, 1000.0, 1000.0],
            "is_normal": [True, True, True, False],
        }
    )


RATED = pd.Series({"T01": 2000.0})


def test_monthly_residuals_average_normal_rows_per_month() -> None:
    monthly = db.monthly_residuals(two_years(), RATED)

    assert (
        [str(m) for m in monthly.columns],
        monthly.loc["T01"].round(3).tolist(),
    ) == (["2022-12", "2023-01"], [-0.1, 0.0])


def test_yearly_summary_counts_energy_normal_share_and_alerts() -> None:
    alerts = pd.DataFrame(
        {
            "turbine_id": ["T01"],
            "start": [pd.Timestamp("2022-12-01", tz="UTC")],
            "lost_energy_mwh": [1.5],
        }
    )

    summary = db.yearly_summary(two_years(), alerts, RATED, interval_minutes=60)
    assert summary.round(3).to_dict("records") == [
        {
            "turbine_id": "T01",
            "year": 2022,
            "energy_mwh": 1.6,
            "normal_share": 1.0,
            "mean_residual_fraction": -0.1,
            "alerts": 1,
            "alert_lost_mwh": 1.5,
        },
        {
            "turbine_id": "T01",
            "year": 2023,
            "energy_mwh": 1.0,
            "normal_share": 0.5,
            "mean_residual_fraction": 0.0,
            "alerts": 0,
            "alert_lost_mwh": 0.0,
        },
    ]


def test_in_training_up_to_and_including_train_end() -> None:
    assert [db.in_training(ts(m), "2022-10-01 00:10") for m in (0, 10, 20)] == [
        True,
        True,
        False,
    ]


def test_training_span_clips_window_to_training_period() -> None:
    train_end = "2022-10-01 00:20"

    assert [
        db.training_span(ts(0), ts(10), train_end),
        db.training_span(ts(10), ts(40), train_end),
        db.training_span(ts(30), ts(40), train_end),
    ] == [(ts(0), ts(10)), (ts(10), ts(20)), None]


def test_training_months_counts_months_up_to_train_end() -> None:
    months = pd.period_range("2021-11", "2022-02", freq="M")

    assert db.training_months(months, "2021-12-31 23:50") == 2
