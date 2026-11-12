"""Streamlit dashboard replaying the Kelmarsh digital twin over 2022.

Structure (turbines, sensors, models, alerts) comes from the RDF graph;
time series come from Parquet via DuckDB.
"""

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pandas as pd  # noqa: E402
import plotly.express as px  # noqa: E402
import plotly.graph_objects as go  # noqa: E402
import streamlit as st  # noqa: E402

from src import dashboard as db  # noqa: E402
from src.config import load_config  # noqa: E402
from src.graph_utils import (  # noqa: E402
    SENSORS_QUERY,
    get_alerts,
    get_models,
    get_sensors,
    get_turbines,
    load_graph,
    parquet_path_of,
)

SPEEDS = [1, 6, 24]
TICK_SECONDS = 0.5
CHART_DAYS = 7
ATTRIBUTION = (
    "Data: Kelmarsh wind farm data by Cubico Sustainable Investments Ltd, "
    "DOI [10.5281/zenodo.16807551](https://doi.org/10.5281/zenodo.16807551), "
    "licensed under [CC-BY-4.0](https://creativecommons.org/licenses/by/4.0/)."
)


@st.cache_data
def read_structure(ontology: str) -> dict[str, pd.DataFrame]:
    """Turbines, models, alerts and per-turbine sensors from the graph."""
    g = load_graph(ontology)
    turbines = get_turbines(g)
    sensors = pd.concat([get_sensors(g, tid) for tid in turbines["turbine_id"]])
    return {
        "turbines": turbines,
        "models": get_models(g),
        "alerts": get_alerts(g),
        "sensors": sensors,
    }


@st.cache_data
def read_series(parquet_paths: tuple[str, ...]) -> pd.DataFrame:
    """All replay time series, read once through DuckDB."""
    return db.load_series(list(parquet_paths))


def to_naive(ts: pd.Timestamp) -> object:
    """UTC timestamp as a naive datetime for the slider."""
    return ts.tz_convert("UTC").tz_localize(None).to_pydatetime()


def set_playing(playing: bool) -> None:
    """Button callback: start or stop the replay."""
    st.session_state.playing = playing


def status_map(turbines: pd.DataFrame, statuses: dict[str, str]) -> go.Figure:
    """Map of the turbines coloured by their current status."""
    data = turbines.assign(status=turbines["turbine_id"].map(statuses))
    fig = px.scatter_map(
        data,
        lat="lat",
        lon="long",
        color="status",
        color_discrete_map=db.STATUS_COLOURS,
        category_orders={"status": list(db.STATUS_COLOURS)},
        hover_name="turbine_id",
        text="turbine_id",
        zoom=13.5,
        height=320,
        map_style="carto-positron",
    )
    fig.update_traces(marker={"size": 18}, textposition="top right")
    fig.update_layout(margin={"l": 0, "r": 0, "t": 0, "b": 0})
    return fig


def power_chart(
    recent: pd.DataFrame, alerts: pd.DataFrame, start: pd.Timestamp, end: pd.Timestamp
) -> go.Figure:
    """Actual and expected power with alert periods shaded."""
    fig = go.Figure()
    for column, name in [("power", "Actual"), ("expected_power", "Expected")]:
        fig.add_scatter(
            x=recent["timestamp"], y=recent[column], name=name, mode="lines"
        )
    for alert in db.alerts_overlapping(alerts, start, end).itertuples():
        fig.add_vrect(
            x0=max(alert.start, start),
            x1=min(alert.end, end),
            fillcolor=db.STATUS_COLOURS["alert"],
            opacity=0.15,
            line_width=0,
        )
    fig.update_layout(
        height=330,
        margin={"l": 0, "r": 0, "t": 30, "b": 0},
        yaxis_title="Power (kW)",
        title=f"Last {CHART_DAYS} days (alert periods shaded)",
    )
    return fig


def power_curve(frame: pd.DataFrame, current: pd.Series | None) -> go.Figure:
    """Power curve of normal rows with the current sample highlighted."""
    normal = frame[frame["is_normal"]]
    fig = go.Figure()
    fig.add_scattergl(
        x=normal["wind_speed"],
        y=normal["power"],
        mode="markers",
        marker={"size": 2, "color": "#90a4ae", "opacity": 0.4},
        name="Normal samples",
    )
    if current is not None:
        fig.add_scatter(
            x=[current["wind_speed"]],
            y=[current["power"]],
            mode="markers",
            marker={"size": 14, "color": db.STATUS_COLOURS["alert"]},
            name="Current",
        )
    fig.update_layout(
        height=330,
        margin={"l": 0, "r": 0, "t": 30, "b": 0},
        xaxis_title="Wind speed (m/s)",
        yaxis_title="Power (kW)",
        title="Power curve",
    )
    return fig


def fmt(value: float | None, pattern: str) -> str:
    """Format a KPI value, showing a dash when missing."""
    return "–" if value is None or pd.isna(value) else pattern.format(value)


def main() -> None:
    """Render the dashboard and advance the replay when playing."""
    st.set_page_config(page_title="Kelmarsh Digital Twin", layout="wide")
    config = load_config()
    structure = read_structure(config["paths"]["ontology"])
    turbines, alerts = structure["turbines"], structure["alerts"]
    sensors = structure["sensors"]
    paths = tuple(
        str(parquet_path_of(sensors[sensors["turbine_id"] == tid]))
        for tid in turbines["turbine_id"]
    )
    series = read_series(paths)
    first, last = series["timestamp"].min(), series["timestamp"].max()
    interval = config["sampling"]["interval_minutes"]

    st.session_state.setdefault("playing", False)
    st.session_state.setdefault("replay_time", to_naive(first))

    st.sidebar.header("Replay")
    turbine_id = st.sidebar.selectbox("Turbine", turbines["turbine_id"])
    speed = st.sidebar.radio("Speed (samples per tick)", SPEEDS, horizontal=True)
    play_col, pause_col = st.sidebar.columns(2)
    play_col.button("▶ Play", on_click=set_playing, args=(True,), width="stretch")
    pause_col.button("⏸ Pause", on_click=set_playing, args=(False,), width="stretch")
    if st.session_state.playing:
        ts = pd.Timestamp(st.session_state.replay_time, tz="UTC")
        nxt, keep = db.advance(ts, speed, interval, last)
        st.session_state.replay_time = to_naive(nxt)
        st.session_state.playing = keep
    st.sidebar.slider(
        "Replay time (UTC)",
        min_value=to_naive(first),
        max_value=to_naive(last),
        step=pd.Timedelta(minutes=interval).to_pytimedelta(),
        format="YYYY-MM-DD HH:mm",
        key="replay_time",
    )
    st.sidebar.caption("Playing" if st.session_state.playing else "Paused")
    ts = pd.Timestamp(st.session_state.replay_time, tz="UTC")

    frames = {tid: f for tid, f in series.groupby("turbine_id")}
    alerts_by = {tid: alerts[alerts["turbine_id"] == tid] for tid in frames}
    statuses = {
        tid: db.turbine_status(db.row_at(f, ts), ts, alerts_by[tid])
        for tid, f in frames.items()
    }

    st.title("Kelmarsh Wind Farm Digital Twin")
    st.caption(f"Replay time: {ts:%Y-%m-%d %H:%M} UTC")
    st.plotly_chart(status_map(turbines, statuses), width="stretch")

    turbine = turbines.set_index("turbine_id").loc[turbine_id]
    frame, turbine_alerts = frames[turbine_id], alerts_by[turbine_id]
    current = db.row_at(frame, ts)
    values = db.kpis(current, turbine["rated_power_kw"])
    model = structure["models"].set_index("turbine_id").loc[turbine_id]
    st.subheader(f"{turbine['label']} ({turbine_id}): {statuses[turbine_id]}")
    cols = st.columns(4)
    cols[0].metric("Actual power", fmt(values["power"], "{:,.0f} kW"))
    cols[1].metric("Expected power", fmt(values["expected_power"], "{:,.0f} kW"))
    cols[2].metric("Residual fraction", fmt(values["residual_fraction"], "{:+.1%}"))
    cols[3].metric("Wind speed", fmt(values["wind_speed"], "{:.1f} m/s"))
    st.caption(
        f"Power model nMAE {fmt(model['nmae'], '{:.3f}')} "
        f"(MAE {fmt(model['mae_kw'], '{:.0f}')} kW), rated power "
        f"{turbine['rated_power_kw']:,.0f} kW"
    )

    start = ts - pd.Timedelta(days=CHART_DAYS)
    left, right = st.columns(2)
    left.plotly_chart(
        power_chart(db.window(frame, ts, CHART_DAYS), turbine_alerts, start, ts),
        width="stretch",
    )
    right.plotly_chart(power_curve(frame, current), width="stretch")

    st.subheader("Alerts")
    st.dataframe(
        turbine_alerts[["start", "end", "mean_residual_fraction", "lost_energy_mwh"]]
        .rename(
            columns={
                "mean_residual_fraction": "Mean residual fraction",
                "lost_energy_mwh": "Lost energy (MWh)",
            }
        )
        .round({"Mean residual fraction": 3, "Lost energy (MWh)": 3}),
        hide_index=True,
        width="stretch",
    )

    with st.expander("Ontology view"):
        st.markdown(f"Sensors of `{turbine_id}`, bound as `?turbine_id`:")
        st.code(SENSORS_QUERY.strip(), language="sparql")
        st.dataframe(
            sensors[sensors["turbine_id"] == turbine_id].drop(columns="turbine_id"),
            hide_index=True,
            width="stretch",
        )

    st.divider()
    st.caption(ATTRIBUTION)

    if st.session_state.playing:
        time.sleep(TICK_SECONDS)
        st.rerun()


main()
