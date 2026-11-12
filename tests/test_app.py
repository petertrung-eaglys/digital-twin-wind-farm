"""Smoke test of the Streamlit app against the real pipeline outputs.

Needs `make all` to have produced the Parquet files; skipped otherwise,
because data/ is not part of the repository.
"""

import json
from datetime import datetime
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
