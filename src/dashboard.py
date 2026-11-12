"""Pure helpers for the replay dashboard: data access, status and KPIs."""

from pathlib import Path

import duckdb
import pandas as pd

STATUS_COLOURS = {"normal": "#2e7d32", "not normal": "#ffb300", "alert": "#c62828"}
SERIES_QUERY = """
SELECT timestamp, turbine_id, wind_speed, power, expected_power, is_normal
FROM read_parquet(?)
ORDER BY turbine_id, timestamp
"""


def load_series(parquet_paths: list[str | Path]) -> pd.DataFrame:
    """Read the replay columns of the given Parquet files through DuckDB (UTC)."""
    with duckdb.connect() as con:
        con.execute("SET TimeZone = 'UTC'")
        frame = con.execute(SERIES_QUERY, [[str(p) for p in parquet_paths]]).df()
    return frame.assign(timestamp=pd.to_datetime(frame["timestamp"], utc=True))


def sample_rows(frame: pd.DataFrame, max_rows: int, seed: int = 0) -> pd.DataFrame:
    """At most max_rows rows: a reproducible random sample when there are more."""
    if len(frame) <= max_rows:
        return frame
    return frame.sample(n=max_rows, random_state=seed).sort_index()


def map_center(turbines: pd.DataFrame) -> dict[str, float]:
    """Mean turbine position; plotly's scatter_map does not centre itself."""
    return {"lat": float(turbines["lat"].mean()), "lon": float(turbines["long"].mean())}


def row_at(frame: pd.DataFrame, ts: pd.Timestamp) -> pd.Series | None:
    """The latest row at or before ts, or None if there is none."""
    before = frame[frame["timestamp"] <= ts]
    return None if before.empty else before.iloc[-1]


def in_alert(ts: pd.Timestamp, alerts: pd.DataFrame) -> bool:
    """True if ts falls inside any alert period."""
    return bool(((alerts["start"] <= ts) & (ts <= alerts["end"])).any())


def active_alerts(alerts: pd.DataFrame, ts: pd.Timestamp) -> set[str]:
    """IRIs of the alerts whose period contains ts."""
    inside = (alerts["start"] <= ts) & (ts <= alerts["end"])
    return set(alerts.loc[inside, "alert"])


def turbine_status(
    row: pd.Series | None, ts: pd.Timestamp, alerts: pd.DataFrame
) -> str:
    """'alert' inside an alert period, else 'normal' or 'not normal'."""
    if in_alert(ts, alerts):
        return "alert"
    return "normal" if row is not None and bool(row["is_normal"]) else "not normal"


def window(frame: pd.DataFrame, end: pd.Timestamp, days: int) -> pd.DataFrame:
    """Rows in the last `days` days up to and including end."""
    start = end - pd.Timedelta(days=days)
    return frame[(frame["timestamp"] > start) & (frame["timestamp"] <= end)]


def alerts_overlapping(
    alerts: pd.DataFrame, start: pd.Timestamp, end: pd.Timestamp
) -> pd.DataFrame:
    """Alerts whose period overlaps [start, end]."""
    return alerts[(alerts["start"] <= end) & (alerts["end"] >= start)]


def kpis(row: pd.Series | None, rated_power_kw: float) -> dict[str, float | None]:
    """Actual and expected power, residual fraction and wind speed of a row."""
    if row is None:
        return dict.fromkeys(
            ["power", "expected_power", "residual_fraction", "wind_speed"]
        )
    residual = (row["power"] - row["expected_power"]) / rated_power_kw
    return {
        "power": row["power"],
        "expected_power": row["expected_power"],
        "residual_fraction": residual,
        "wind_speed": row["wind_speed"],
    }


def advance(
    ts: pd.Timestamp, samples: int, interval_minutes: int, last: pd.Timestamp
) -> tuple[pd.Timestamp, bool]:
    """Move ts forward by samples; return the new time and whether to keep playing."""
    nxt = ts + pd.Timedelta(minutes=samples * interval_minutes)
    return (nxt, True) if nxt < last else (last, False)


def clamp(ts: pd.Timestamp, first: pd.Timestamp, last: pd.Timestamp) -> pd.Timestamp:
    """ts limited to [first, last]."""
    return min(max(ts, first), last)


def replay_start(
    first: pd.Timestamp,
    last: pd.Timestamp,
    train_end: str,
    interval_minutes: int,
) -> pd.Timestamp:
    """First sample of the test period (after train_end), within the data."""
    start = pd.Timestamp(train_end, tz="UTC") + pd.Timedelta(minutes=interval_minutes)
    return clamp(start, first, last)


def in_training(ts: pd.Timestamp, train_end: str) -> bool:
    """True if ts lies in the model's training period (up to train_end)."""
    return ts <= pd.Timestamp(train_end, tz="UTC")


def training_span(
    start: pd.Timestamp, end: pd.Timestamp, train_end: str
) -> tuple[pd.Timestamp, pd.Timestamp] | None:
    """Part of [start, end] inside the training period, or None."""
    boundary = pd.Timestamp(train_end, tz="UTC")
    return None if start > boundary else (start, min(end, boundary))


def training_months(months: pd.Index, train_end: str) -> int:
    """Number of monthly periods up to and including train_end's month."""
    return int((months <= pd.Period(train_end, freq="M")).sum())


def year_span(first_year: int, last_year: int) -> tuple[pd.Timestamp, pd.Timestamp]:
    """First and last instant (UTC) of the years first_year..last_year."""
    end = pd.Timestamp(f"{last_year + 1}-01-01", tz="UTC") - pd.Timedelta(1, "ns")
    return pd.Timestamp(f"{first_year}-01-01", tz="UTC"), end


def rows_between(
    frame: pd.DataFrame, start: pd.Timestamp, end: pd.Timestamp
) -> pd.DataFrame:
    """Rows with start <= timestamp <= end."""
    return frame[frame["timestamp"].between(start, end)]


def with_residual(series: pd.DataFrame, rated_power_kw: pd.Series) -> pd.DataFrame:
    """Series plus residual fraction of each turbine's rated power."""
    rated = series["turbine_id"].map(rated_power_kw)
    return series.assign(
        residual_fraction=(series["power"] - series["expected_power"]) / rated
    )


def monthly_residuals(series: pd.DataFrame, rated_power_kw: pd.Series) -> pd.DataFrame:
    """Mean residual fraction of normal rows per turbine (rows) and month."""
    normal = with_residual(series[series["is_normal"]], rated_power_kw)
    month = normal["timestamp"].dt.tz_localize(None).dt.to_period("M")
    return normal.pivot_table(
        index="turbine_id",
        columns=month.rename("month"),
        values="residual_fraction",
        aggfunc="mean",
    )


def yearly_summary(
    series: pd.DataFrame,
    alerts: pd.DataFrame,
    rated_power_kw: pd.Series,
    interval_minutes: int,
) -> pd.DataFrame:
    """Energy, normal share, mean residual and alerts per turbine and year.

    Alerts count towards the year they start in.
    """
    hours = interval_minutes / 60
    data = with_residual(series, rated_power_kw).assign(
        year=series["timestamp"].dt.year,
        energy_mwh=series["power"] * hours / 1000,
        normal_residual=lambda d: d["residual_fraction"].where(d["is_normal"]),
    )
    per_year = data.groupby(["turbine_id", "year"]).agg(
        energy_mwh=("energy_mwh", "sum"),
        normal_share=("is_normal", "mean"),
        mean_residual_fraction=("normal_residual", "mean"),
    )
    alert_stats = (
        alerts.assign(year=alerts["start"].dt.year)
        .groupby(["turbine_id", "year"])
        .agg(alerts=("start", "size"), alert_lost_mwh=("lost_energy_mwh", "sum"))
    )
    return (
        per_year.join(alert_stats)
        .fillna({"alerts": 0, "alert_lost_mwh": 0.0})
        .astype({"alerts": int})
        .reset_index()
    )
