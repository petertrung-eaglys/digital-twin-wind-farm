"""Tests for graph persistence, model and alert helpers."""

from datetime import UTC, datetime
from pathlib import Path

import pandas as pd
from rdflib import Graph

from src.graph_utils import (
    KT,
    PROV,
    add_alert,
    add_model,
    get_alerts,
    get_lineage,
    get_schema,
    load_graph,
    model_iri,
    save_graph,
    turbine_iri,
)
from src.ontology_view import qname

START = datetime(2022, 10, 3, 0, 0, tzinfo=UTC)
END = datetime(2022, 10, 4, 6, 0, tzinfo=UTC)


def test_save_and_load_round_trip(graph: Graph, tmp_path: Path) -> None:
    path = tmp_path / "out" / "g.ttl"
    save_graph(graph, path)

    assert len(load_graph(path)) == len(graph)


def test_saved_file_starts_with_schema(graph: Graph, tmp_path: Path) -> None:
    path = tmp_path / "g.ttl"
    save_graph(graph, path)
    text = path.read_text(encoding="utf-8")

    assert text.index("rdfs:Class") < text.index("kt:T01 ")


def test_add_model_replaces_previous_node(graph: Graph) -> None:
    inputs = ["wind_speed"]
    add_model(graph, "T01", inputs, "power", {"mae_kw": 50.0, "nmae": 0.02}, START)
    add_model(graph, "T01", inputs, "power", {"mae_kw": 40.0, "nmae": 0.01}, END)

    model = model_iri("T01")
    assert (
        [float(o) for o in graph.objects(model, KT.maeKW)],
        list(graph.objects(model, PROV.generatedAtTime))[0].toPython(),
        len(list(graph.objects(model, KT.usesInput))),
    ) == ([40.0], END, 1)


def test_add_alert_is_returned_by_get_alerts(graph: Graph) -> None:
    add_alert(graph, "T02", 1, pd.Timestamp(START), pd.Timestamp(END), -0.08, 3.5)

    alerts = get_alerts(graph, "T02")
    assert alerts[
        [
            "turbine_id",
            "model",
            "start",
            "end",
            "mean_residual_fraction",
            "lost_energy_mwh",
        ]
    ].to_dict("records") == [
        {
            "turbine_id": "T02",
            "model": str(model_iri("T02")),
            "start": pd.Timestamp(START),
            "end": pd.Timestamp(END),
            "mean_residual_fraction": -0.08,
            "lost_energy_mwh": 3.5,
        }
    ]


def test_get_alerts_filters_by_turbine(graph: Graph) -> None:
    add_alert(graph, "T01", 1, START, END, -0.1, 1.0)
    add_alert(graph, "T02", 1, START, END, -0.1, 1.0)

    assert (len(get_alerts(graph)), len(get_alerts(graph, "T01"))) == (2, 1)


def test_get_alerts_empty_has_columns(graph: Graph) -> None:
    alerts = get_alerts(graph, "T01")

    assert (len(alerts), "lost_energy_mwh" in alerts.columns) == (0, True)


def test_saved_file_uses_spec_prefixes(graph: Graph, tmp_path: Path) -> None:
    path = tmp_path / "g.ttl"
    save_graph(graph, path)
    text = path.read_text(encoding="utf-8")

    assert "@prefix geo: <http://www.w3.org/2003/01/geo/wgs84_pos#> ." in text


def test_add_model_records_model_file(graph: Graph) -> None:
    add_model(graph, "T01", ["wind_speed"], "power", model_file="models/power_T01.txt")

    assert str(graph.value(model_iri("T01"), KT.modelFile)) == "models/power_T01.txt"


def test_lineage_covers_turbine_and_its_sources_only(graph: Graph) -> None:
    nodes = {qname(s) for s in get_lineage(graph, "T01")["s"]}

    assert (
        {
            "kt:Kelmarsh",
            "kt:T01",
            "kt:T01_Rotor",
            "kt:T01_power",
            "kt:PowerModel_T01",
            "kt:Source_Kelmarsh_WT_static_csv",
            "kt:Source_Kelmarsh_SCADA_2022_4457_zip",
            "kt:Dataset_Kelmarsh",
        }
        <= nodes,
        {n for n in nodes if "T02" in n},
    ) == (True, set())


def test_lineage_hides_links_to_other_turbines(graph: Graph) -> None:
    lineage = get_lineage(graph, "T01")
    farm_links = lineage[lineage["s"] == str(KT.Kelmarsh)]

    assert str(turbine_iri("T02")) not in set(farm_links["o"])


def test_schema_has_source_classes_under_prov_entity(graph: Graph) -> None:
    classes, properties = get_schema(graph)
    parents = classes.set_index("class")["parent"]

    assert (
        parents[str(KT.Dataset)],
        parents[str(KT.SourceFile)],
        str(PROV.wasDerivedFrom) in set(properties["property"]),
    ) == (str(PROV.Entity), str(PROV.Entity), True)
