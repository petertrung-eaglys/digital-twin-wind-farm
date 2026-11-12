"""Tests for the ontology builder, checked through SPARQL helpers."""

import pandas as pd
import pytest
from rdflib import RDF, RDFS, Graph, Literal

from src.build_ontology import (
    add_schema,
    mapping_entry,
    strip_unit,
    turbine_id_from_title,
    turbines_from_static,
)
from src.graph_utils import KT, get_model_inputs, get_sensors, get_turbines, new_graph
from src.graph_utils import sensor_iri as sensor


def test_strip_unit_drops_only_trailing_unit() -> None:
    assert [
        strip_unit("Power (kW)"),
        strip_unit("Ambient temperature (converter) (°C)"),
        strip_unit("Capacity factor"),
    ] == ["Power", "Ambient temperature (converter)", "Capacity factor"]


def test_turbine_id_from_title() -> None:
    assert turbine_id_from_title("Kelmarsh 6") == "T06"


def test_turbine_id_from_title_rejects_unknown_title() -> None:
    with pytest.raises(ValueError, match="No turbine number"):
        turbine_id_from_title("Kelmarsh")


def test_turbines_from_static_keeps_real_values(static: pd.DataFrame) -> None:
    second = turbines_from_static(static)[1]

    assert (second["turbine_id"], second["lat"], second["hub_height_m"]) == (
        "T02",
        52.41,
        68.5,
    )


def test_mapping_entry_matches_by_title_without_unit(mapping: pd.DataFrame) -> None:
    assert mapping_entry(mapping, "Power (kW)")["Greenbyte Signal ID"] == 5


def test_mapping_entry_is_none_without_match(mapping: pd.DataFrame) -> None:
    assert mapping_entry(mapping, "Rotor speed (RPM)") is None


def test_schema_terms_all_have_label_and_comment() -> None:
    g = new_graph()
    add_schema(g)
    terms = set(g.subjects(RDF.type, RDFS.Class)) | set(
        g.subjects(RDF.type, RDF.Property)
    )

    unlabelled = [
        t
        for t in terms
        if (t, RDFS.label, None) not in g or (t, RDFS.comment, None) not in g
    ]
    assert unlabelled == []


def test_graph_has_turbines_with_coordinates(graph: Graph) -> None:
    turbines = get_turbines(graph)

    assert turbines[["turbine_id", "lat", "rated_power_kw"]].to_dict("records") == [
        {"turbine_id": "T01", "lat": 52.40, "rated_power_kw": 2050.0},
        {"turbine_id": "T02", "lat": 52.41, "rated_power_kw": 2050.0},
    ]


def test_each_turbine_has_seven_sensors(graph: Graph) -> None:
    counts = [len(get_sensors(graph, tid)) for tid in ("T01", "T02")]

    assert counts == [7, 7]


def test_sensors_attached_to_spec_components(graph: Graph) -> None:
    sensors = get_sensors(graph, "T01").set_index("signal_key")["component"]

    assert {k: v.split("#")[1] for k, v in sensors.items()} == {
        "ambient_temp": "Nacelle",
        "nacelle_direction": "Nacelle",
        "pitch": "Rotor",
        "power": "Generator",
        "rotor_speed": "Rotor",
        "wind_direction": "Nacelle",
        "wind_speed": "Nacelle",
    }


def test_sensor_points_to_turbine_parquet(graph: Graph) -> None:
    sensors = get_sensors(graph, "T02").set_index("signal_key")

    assert sensors.loc["power", "parquet_path"] == "data/processed/scada_T02.parquet"


def test_mapping_title_recorded_only_where_matched(graph: Graph) -> None:
    titles = [
        graph.value(sensor("T01", key), KT.manufacturerTitle)
        for key in ("power", "rotor_speed")
    ]

    assert titles == [Literal("Actual value of active power"), None]


def test_model_inputs_come_from_config(graph: Graph) -> None:
    assert get_model_inputs(graph, "T01") == [
        "ambient_temp",
        "wind_direction",
        "wind_speed",
    ]
