"""Streamlit dashboard replaying the Kelmarsh digital twin over 2016-2024.

Structure (turbines, sensors, models, alerts) comes from the RDF graph;
time series come from Parquet via DuckDB.
"""

import sys
import time
from datetime import datetime, timedelta
from datetime import time as clock_time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pandas as pd  # noqa: E402
import plotly.express as px  # noqa: E402
import plotly.graph_objects as go  # noqa: E402
import streamlit as st  # noqa: E402

from src import dashboard as db  # noqa: E402
from src.config import load_config  # noqa: E402
from src.graph_utils import (  # noqa: E402
    LINEAGE_QUERY,
    SCHEMA_CLASSES_QUERY,
    SCHEMA_PROPERTIES_QUERY,
    SENSORS_QUERY,
    get_alerts,
    get_lineage,
    get_models,
    get_schema,
    get_sensors,
    get_turbines,
    load_graph,
    parquet_path_of,
)
from src.ontology_view import lineage_dot, schema_dot, without_sensors  # noqa: E402

# Samples (10 minutes each) advanced per tick, by label
SPEEDS = {"10 min": 1, "1 h": 6, "4 h": 24, "1 day": 144, "1 week": 1008}
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
def read_lineage(ontology: str, turbine_id: str) -> pd.DataFrame:
    """Lineage triples of one turbine from the graph."""
    return get_lineage(load_graph(ontology), turbine_id)


@st.cache_data
def read_schema_dot(ontology: str) -> str:
    """DOT class diagram of the graph's schema."""
    return schema_dot(*get_schema(load_graph(ontology)))


@st.cache_data
def read_series(parquet_paths: tuple[str, ...]) -> pd.DataFrame:
    """All replay time series, read once through DuckDB."""
    return db.load_series(list(parquet_paths))


@st.cache_data
def read_overview(
    ontology: str, parquet_paths: tuple[str, ...], interval_minutes: int
) -> dict[str, pd.DataFrame]:
    """Monthly residuals and yearly summary of all turbines (computed once)."""
    structure = read_structure(ontology)
    series = read_series(parquet_paths)
    rated = structure["turbines"].set_index("turbine_id")["rated_power_kw"]
    return {
        "monthly": db.monthly_residuals(series, rated),
        "yearly": db.yearly_summary(
            series, structure["alerts"], rated, interval_minutes
        ),
    }


def to_naive(ts: pd.Timestamp) -> datetime:
    """UTC timestamp as a naive datetime for the widgets."""
    return ts.tz_convert("UTC").tz_localize(None).to_pydatetime()


def set_playing(playing: bool) -> None:
    """Button callback: start or stop the replay."""
    st.session_state.playing = playing


def set_replay_time(first: pd.Timestamp, last: pd.Timestamp) -> None:
    """Date/clock callback: replay time from the picked date and time of day."""
    state = st.session_state
    picked = datetime.combine(state.replay_date, state.replay_clock)
    st.session_state.replay_time = to_naive(
        db.clamp(pd.Timestamp(picked, tz="UTC"), first, last)
    )


def status_map(
    turbines: pd.DataFrame, statuses: dict[str, str], map_style: str
) -> go.Figure:
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
        center=db.map_center(turbines),
        zoom=13.5,
        height=320,
        map_style=map_style,
    )
    fig.update_traces(
        marker={"size": 18},
        textposition="top right",
        textfont={"color": "white", "size": 14},
    )
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


def power_curve(
    frame: pd.DataFrame, current: pd.Series | None, max_points: int, years: str
) -> go.Figure:
    """Power curve of (a sample of) normal rows, current sample highlighted."""
    normal = db.sample_rows(frame[frame["is_normal"]], max_points)
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
        title=f"Power curve {years} (up to {max_points:,} normal samples)",
    )
    return fig


def fmt(value: float | None, pattern: str) -> str:
    """Format a KPI value, showing a dash when missing."""
    return "–" if value is None or pd.isna(value) else pattern.format(value)


def years_label(years: tuple[int, int]) -> str:
    """'2022' for a single year, '2016–2024' for a range."""
    first, last = years
    return str(first) if first == last else f"{first}–{last}"


def residual_heatmap(monthly: pd.DataFrame) -> go.Figure:
    """Monthly mean residual fraction per turbine; red is underperformance."""
    fig = go.Figure(
        go.Heatmap(
            z=monthly.to_numpy(),
            x=[str(month) for month in monthly.columns],
            y=list(monthly.index),
            colorscale="RdBu",
            zmid=0,
            colorbar={"title": "Residual", "tickformat": "+.0%"},
            hovertemplate="%{y} %{x}: %{z:+.1%}<extra></extra>",
        )
    )
    fig.update_layout(
        height=300,
        margin={"l": 0, "r": 0, "t": 30, "b": 0},
        title="Mean residual fraction of normal rows per month",
    )
    return fig


def render_overview(overview: dict[str, pd.DataFrame], turbine_id: str) -> None:
    """The overview tab: monthly residuals of all turbines, yearly summary."""
    st.plotly_chart(residual_heatmap(overview["monthly"]), width="stretch")
    st.caption(
        "Residual = (actual - expected power) / rated power. The model was "
        "trained on the earlier years, so residuals there are in-sample."
    )
    st.subheader(f"Yearly summary of {turbine_id}")
    yearly = overview["yearly"]
    st.dataframe(
        yearly[yearly["turbine_id"] == turbine_id]
        .drop(columns="turbine_id")
        .rename(
            columns={
                "year": "Year",
                "energy_mwh": "Energy (MWh)",
                "normal_share": "Normal share",
                "mean_residual_fraction": "Mean residual fraction",
                "alerts": "Alerts",
                "alert_lost_mwh": "Lost energy in alerts (MWh)",
            }
        )
        .round(
            {
                "Energy (MWh)": 0,
                "Normal share": 3,
                "Mean residual fraction": 3,
                "Lost energy in alerts (MWh)": 1,
            }
        ),
        hide_index=True,
        width="stretch",
    )


def render_replay(
    structure: dict[str, pd.DataFrame],
    frames: dict[str, pd.DataFrame],
    alerts_by: dict[str, pd.DataFrame],
    statuses: dict[str, str],
    turbine_id: str,
    ts: pd.Timestamp,
    years: tuple[int, int],
    dashboard_config: dict,
) -> None:
    """The replay tab: map, KPIs, charts, alerts and the sensors query.

    The power curve and the alerts table only cover the selected years.
    """
    turbines, sensors = structure["turbines"], structure["sensors"]
    st.plotly_chart(
        status_map(turbines, statuses, dashboard_config["map_style"]),
        width="stretch",
    )

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
    span = db.year_span(*years)
    label = years_label(years)
    left, right = st.columns(2)
    left.plotly_chart(
        power_chart(db.window(frame, ts, CHART_DAYS), turbine_alerts, start, ts),
        width="stretch",
    )
    right.plotly_chart(
        power_curve(
            db.rows_between(frame, *span),
            current,
            dashboard_config["power_curve_max_points"],
            label,
        ),
        width="stretch",
    )

    st.subheader(f"Alerts {label}")
    shown_alerts = db.alerts_overlapping(turbine_alerts, *span)
    st.dataframe(
        shown_alerts[["start", "end", "mean_residual_fraction", "lost_energy_mwh"]]
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


def render_ontology(
    ontology: str, turbine_id: str, alerts: pd.DataFrame, ts: pd.Timestamp
) -> None:
    """The ontology tab: lineage of the selected turbine and the schema."""
    st.subheader(f"Lineage of {turbine_id}")
    st.markdown(
        "Where the turbine's specs and readings come from: specs are derived "
        "from the static CSV, each sensor from its raw SCADA file (inside the "
        "Zenodo archive) and, where matched, the signal mapping CSV. Alerts "
        "inside the replay time are red."
    )
    triples = read_lineage(ontology, turbine_id)
    keys = sorted(triples.loc[triples["p"].str.endswith("#signalKey"), "o"].astype(str))
    shown = st.multiselect("Sensors to trace", keys, default=keys)
    st.graphviz_chart(
        lineage_dot(without_sensors(triples, set(shown)), db.active_alerts(alerts, ts)),
        width="stretch",
    )
    with st.expander("Lineage SPARQL query"):
        st.code(LINEAGE_QUERY.strip(), language="sparql")
    st.subheader("Ontology schema")
    st.graphviz_chart(read_schema_dot(ontology), width="stretch")
    with st.expander("Schema SPARQL queries"):
        st.code(SCHEMA_CLASSES_QUERY.strip(), language="sparql")
        st.code(SCHEMA_PROPERTIES_QUERY.strip(), language="sparql")


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

    start = db.replay_start(
        first, last, config["train_test_split"]["train_end"], interval
    )
    st.session_state.setdefault("playing", False)
    st.session_state.setdefault("replay_time", to_naive(start))

    st.sidebar.header("Replay")
    turbine_id = st.sidebar.selectbox("Turbine", turbines["turbine_id"])
    speed = st.sidebar.radio("Speed (per tick)", list(SPEEDS), horizontal=True)
    play_col, pause_col = st.sidebar.columns(2)
    play_col.button("▶ Play", on_click=set_playing, args=(True,), width="stretch")
    pause_col.button("⏸ Pause", on_click=set_playing, args=(False,), width="stretch")
    if st.session_state.playing:
        ts = pd.Timestamp(st.session_state.replay_time, tz="UTC")
        nxt, keep = db.advance(ts, SPEEDS[speed], interval, last)
        st.session_state.replay_time = to_naive(nxt)
        st.session_state.playing = keep
    # The date and clock widgets mirror replay_time, which playing advances
    replay_time = st.session_state.replay_time
    st.session_state.replay_date = replay_time.date()
    st.session_state.replay_clock = replay_time.time()
    st.sidebar.date_input(
        "Replay date (UTC)",
        min_value=to_naive(first).date(),
        max_value=to_naive(last).date(),
        key="replay_date",
        on_change=set_replay_time,
        args=(first, last),
    )
    st.sidebar.slider(
        "Time of day (UTC)",
        min_value=clock_time(0, 0),
        max_value=(datetime.min + timedelta(days=1, minutes=-interval)).time(),
        step=pd.Timedelta(minutes=interval).to_pytimedelta(),
        format="HH:mm",
        key="replay_clock",
        on_change=set_replay_time,
        args=(first, last),
    )
    st.sidebar.caption("Playing" if st.session_state.playing else "Paused")
    ts = pd.Timestamp(st.session_state.replay_time, tz="UTC")

    st.sidebar.header("Alerts & power curve")
    all_years = (first.year, last.year)
    if st.sidebar.checkbox("Replay year only", value=True):
        years = (ts.year, ts.year)
    else:
        years = st.sidebar.select_slider(
            "Years", options=list(range(first.year, last.year + 1)), value=all_years
        )

    frames = {tid: f for tid, f in series.groupby("turbine_id")}
    alerts_by = {tid: alerts[alerts["turbine_id"] == tid] for tid in frames}
    statuses = {
        tid: db.turbine_status(db.row_at(f, ts), ts, alerts_by[tid])
        for tid, f in frames.items()
    }

    st.title("Kelmarsh Wind Farm Digital Twin")
    st.caption(f"Replay time: {ts:%Y-%m-%d %H:%M} UTC")
    replay_tab, overview_tab, ontology_tab = st.tabs(
        ["Replay", "Overview", "Ontology & lineage"]
    )
    with replay_tab:
        render_replay(
            structure,
            frames,
            alerts_by,
            statuses,
            turbine_id,
            ts,
            years,
            config["dashboard"],
        )
    with overview_tab:
        render_overview(
            read_overview(config["paths"]["ontology"], paths, interval), turbine_id
        )
    with ontology_tab:
        render_ontology(
            config["paths"]["ontology"], turbine_id, alerts_by[turbine_id], ts
        )

    st.divider()
    st.caption(ATTRIBUTION)

    if st.session_state.playing:
        time.sleep(TICK_SECONDS)
        st.rerun()


main()
