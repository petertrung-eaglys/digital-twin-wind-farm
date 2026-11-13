"""Smoke test of the Streamlit app against the real pipeline outputs.

Needs `make all` to have produced the Parquet files; skipped otherwise,
because data/ is not part of the repository.
"""

import json
from datetime import date, datetime
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

from src.config import load_config

ROOT = Path(__file__).resolve().parent.parent
PROCESSED = ROOT / load_config()["paths"]["processed"]

pytestmark = pytest.mark.skipif(
    not any(PROCESSED.glob("scada_*.parquet")),
    reason="pipeline outputs missing; run `make all` first",
)


def run_app() -> AppTest:
    app = AppTest.from_file(str(ROOT / "app" / "app.py"), default_timeout=60)
    return app.run()


def test_app_renders_without_exceptions() -> None:
    app = run_app()

    assert (len(app.exception), app.title[0].value) == (
        0,
        "Kelmarsh Wind Farm Digital Twin",
    )


def test_app_shows_four_kpis_and_attribution() -> None:
    app = run_app()

    captions = [c.value for c in app.caption]
    assert (len(app.metric), any("Cubico" in c for c in captions)) == (4, True)


def test_replay_time_drives_kpis_and_caption() -> None:
    app = run_app()
    before = [m.value for m in app.metric]
    app.session_state["replay_time"] = datetime(2022, 12, 31, 23, 50)
    app.run()

    assert (
        len(app.exception),
        app.caption[0].value,
        [m.value for m in app.metric] != before,
    ) == (0, "Replay time: 2022-12-31 23:50 UTC", True)


def test_pause_stops_replay_without_advancing() -> None:
    app = run_app()
    start = app.session_state["replay_time"]
    app.session_state["playing"] = True
    app.sidebar.button[1].click().run()

    assert (app.session_state["playing"], app.session_state["replay_time"]) == (
        False,
        start,
    )


def test_status_map_is_centred_on_the_farm() -> None:
    app = run_app()
    status_map = json.loads(app.get("plotly_chart")[0].proto.spec)

    center = status_map["layout"]["map"]["center"]
    assert (round(center["lat"], 1), round(center["lon"], 1)) == (52.4, -0.9)


def test_ontology_tab_shows_lineage_and_schema_graphs() -> None:
    app = run_app()
    graphs = app.get("graphviz_chart")

    assert (
        [t.label for t in app.tabs],
        len(graphs),
        "digraph lineage" in graphs[0].proto.spec,
        "digraph schema" in graphs[1].proto.spec,
    ) == (["Replay", "Overview", "Ontology & lineage"], 2, True, True)


def test_sensor_filter_narrows_lineage() -> None:
    app = run_app()
    app.multiselect[0].set_value(["power"]).run()
    lineage = app.get("graphviz_chart")[0].proto.spec

    assert ("power T01" in lineage, "rotor_speed T01" in lineage) == (True, False)


def test_status_map_uses_configured_style() -> None:
    app = run_app()
    status_map = json.loads(app.get("plotly_chart")[0].proto.spec)

    assert (
        status_map["layout"]["map"]["style"] == load_config()["dashboard"]["map_style"]
    )


def test_replay_opens_at_start_of_test_period() -> None:
    app = run_app()

    assert app.caption[0].value == "Replay time: 2022-01-01 00:00 UTC"


def test_date_picker_moves_replay_and_keeps_time_of_day() -> None:
    app = run_app()
    app.session_state["replay_time"] = datetime(2022, 6, 1, 13, 20)
    app.run()
    app.date_input(key="replay_date").set_value(date(2023, 3, 1)).run()

    assert (len(app.exception), app.caption[0].value) == (
        0,
        "Replay time: 2023-03-01 13:20 UTC",
    )


def test_speeds_include_a_day_and_a_week_per_tick() -> None:
    app = run_app()

    assert app.sidebar.radio[0].options[-2:] == ["1 day", "1 week"]


def test_alerts_table_follows_replay_year_unless_unchecked() -> None:
    app = run_app()
    replay_year = len(app.dataframe[0].value)
    app.sidebar.checkbox[0].uncheck().run()

    assert (
        app.subheader[1].value,
        replay_year < len(app.dataframe[0].value),
    ) == ("Alerts 2016–2024", True)


def test_overview_tab_shows_heatmap_and_yearly_summary() -> None:
    app = run_app()
    charts = [json.loads(c.proto.spec) for c in app.get("plotly_chart")]
    heatmap = next(c for c in charts if c["data"][0]["type"] == "heatmap")
    yearly = next(d.value for d in app.dataframe if "Year" in d.value.columns)

    assert (len(heatmap["data"][0]["y"]), yearly["Year"].tolist()) == (
        6,
        list(range(2016, 2025)),
    )


def test_badge_marks_training_or_test_period() -> None:
    app = run_app()
    test_badge = [m.value for m in app.markdown if "badge" in m.value]
    app.session_state["replay_time"] = datetime(2019, 6, 1, 12, 0)
    app.run()
    training_badge = [m.value for m in app.markdown if "badge" in m.value]

    assert (test_badge, training_badge) == (
        [":blue-badge[Test period: expected power is out-of-sample]"],
        [":gray-badge[Training period: expected power is in-sample]"],
    )


def test_power_chart_shades_training_days_across_the_split() -> None:
    app = run_app()
    app.session_state["replay_time"] = datetime(2022, 1, 3, 0, 0)
    app.run()
    chart = json.loads(app.get("plotly_chart")[1].proto.spec)

    assert [a["text"] for a in chart["layout"]["annotations"]] == ["training period"]


def test_current_point_is_drawn_on_top_of_the_power_curve() -> None:
    app = run_app()
    curve = json.loads(app.get("plotly_chart")[2].proto.spec)

    assert [(t["type"], t["name"]) for t in curve["data"]] == [
        ("scattergl", "Normal samples"),
        ("scattergl", "Current"),
    ]


def test_heatmap_marks_split_between_training_and_test_months() -> None:
    app = run_app()
    charts = [json.loads(c.proto.spec) for c in app.get("plotly_chart")]
    heatmap = next(c for c in charts if c["data"][0]["type"] == "heatmap")
    months = heatmap["data"][0]["x"]
    line = heatmap["layout"]["shapes"][0]

    assert (months[int(line["x0"] + 0.5)], line["x0"] == line["x1"]) == (
        "2022-01",
        True,
    )
