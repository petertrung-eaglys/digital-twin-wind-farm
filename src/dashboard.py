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
