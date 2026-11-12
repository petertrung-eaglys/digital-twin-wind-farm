"""Tests for the Graphviz DOT rendering of lineage and schema."""

import shutil
import subprocess

import pandas as pd
import pytest
from rdflib import Graph

from src.graph_utils import KT, add_alert, alert_iri, get_lineage, get_schema
from src.ontology_view import (
    ACTIVE_ALERT_FILL,
    CLASS_FILLS,
    dot_id,
    html_label,
    lineage_dot,
    main_type,
    qname,
    schema_dot,
    without_sensors,
)


def test_qname_uses_longest_matching_prefix() -> None:
    assert [
        qname("https://example.org/kelmarsh-twin#T01"),
        qname("http://qudt.org/vocab/unit/KiloW"),
        qname("http://other.org/x"),
    ] == ["kt:T01", "unit:KiloW", "http://other.org/x"]


def test_dot_id_escapes_quotes_and_backslashes() -> None:
    assert dot_id('a"b\\c') == '"a\\"b\\\\c"'


def test_html_label_escapes_values() -> None:
    label = html_label("T<1>", "kt:Turbine", [("kt:md5", "a&b")], "#fff")

    assert ("T&lt;1&gt;" in label, "a&amp;b" in label, "T<1>" in label) == (
        True,
        True,
        False,
    )


def test_main_type_prefers_specific_class() -> None:
    assert main_type(["kt:PowerModel", "prov:Entity"]) == "kt:PowerModel"


def test_without_sensors_drops_other_sensors_and_their_links(graph: Graph) -> None:
    triples = without_sensors(get_lineage(graph, "T01"), {"power"})
    sensors = {qname(s) for s in triples.loc[triples["p"] == str(KT.signalKey), "s"]}

    assert (sensors, str(KT.T01_pitch) in set(triples["o"])) == (
        {"kt:T01_power"},
        False,
    )


def test_lineage_dot_draws_specs_source_edge(graph: Graph) -> None:
    dot = lineage_dot(get_lineage(graph, "T01"), set())

    assert (
        f"{dot_id(str(KT.T01))} -> {dot_id(str(KT.Source_Kelmarsh_WT_static_csv))}"
        ' [label="prov:wasDerivedFrom"];'
    ) in dot


def test_lineage_dot_shows_literals_as_rows(graph: Graph) -> None:
    dot = lineage_dot(get_lineage(graph, "T01"), set())

    assert ('<TD ALIGN="LEFT">kt:scadaColumn</TD>' in dot, "Power (kW)" in dot) == (
        True,
        True,
    )


def test_lineage_dot_colours_active_alert_red(graph: Graph) -> None:
    add_alert(
        graph,
        "T01",
        1,
        pd.Timestamp("2022-10-01", tz="UTC"),
        pd.Timestamp("2022-10-02", tz="UTC"),
        -0.1,
        1.0,
    )
    alert = str(alert_iri("T01", 1))
    triples = get_lineage(graph, "T01")

    active, idle = lineage_dot(triples, {alert}), lineage_dot(triples, set())
    assert (ACTIVE_ALERT_FILL in active, ACTIVE_ALERT_FILL in idle) == (True, False)


def test_schema_dot_has_subclass_and_relation_edges(graph: Graph) -> None:
    dot = schema_dot(*get_schema(graph))

    assert (
        f"{dot_id(str(KT.Rotor))} -> {dot_id(str(KT.Component))}" in dot,
        'label="kt:hasSensor"' in dot,
        CLASS_FILLS["kt:Turbine"] in dot,
    ) == (True, True, True)


@pytest.mark.skipif(shutil.which("dot") is None, reason="Graphviz not installed")
def test_generated_dot_is_valid_graphviz(graph: Graph) -> None:
    for dot in (
        lineage_dot(get_lineage(graph, "T01"), set()),
        schema_dot(*get_schema(graph)),
    ):
        result = subprocess.run(
            ["dot", "-Tsvg"], input=dot, capture_output=True, text=True, check=False
        )
        assert (result.returncode, result.stderr) == (0, "")
