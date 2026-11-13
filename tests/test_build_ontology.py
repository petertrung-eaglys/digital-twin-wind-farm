"""Tests for the ontology builder, checked through SPARQL helpers."""

from datetime import date

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
from src.graph_utils import (
    DATASET_IRI,
    KT,
    PROV,
    get_model_inputs,
    get_sensors,
    get_turbines,
    new_graph,
    source_iri,
    turbine_iri,
)
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


def test_turbine_specs_traced_to_static_file(graph: Graph) -> None:
    sources = set(graph.objects(turbine_iri("T01"), PROV.wasDerivedFrom))

    assert sources == {source_iri("Kelmarsh_WT_static.csv")}


def test_sensor_readings_traced_to_raw_file_and_mapping(graph: Graph) -> None:
    raw = source_iri("Turbine_Data_Kelmarsh_2_2022-01-01_-_2023-01-01_229.csv")
    mapping_csv = source_iri("Kelmarsh_WT_dataSignalMapping.csv")

    assert [
        set(graph.objects(sensor("T02", key), PROV.wasDerivedFrom))
        for key in ("power", "rotor_speed")
    ] == [{raw, mapping_csv}, {raw}]


def test_raw_file_chain_reaches_dataset(graph: Graph) -> None:
    raw = source_iri("Turbine_Data_Kelmarsh_1_2022-01-01_-_2023-01-01_228.csv")
    archive = graph.value(raw, KT.partOf)

    assert (
        archive,
        graph.value(archive, KT.partOf),
        str(graph.value(DATASET_IRI, KT.doi)),
    ) == (
        source_iri("Kelmarsh_SCADA_2022_4457.zip"),
        DATASET_IRI,
        "10.5281/zenodo.16807551",
    )


def test_downloaded_files_record_url_and_md5(graph: Graph) -> None:
    static_csv = source_iri("Kelmarsh_WT_static.csv")

    assert (
        str(graph.value(static_csv, KT.downloadUrl)),
        str(graph.value(static_csv, KT.md5)),
    ) == ("https://zenodo.org/Kelmarsh_WT_static.csv", "0" * 32)


def test_turbine_has_machine_specs_from_static(graph: Graph) -> None:
    node = turbine_iri("T01")

    assert (
        str(graph.value(node, KT.manufacturer)),
        str(graph.value(node, KT.turbineModel)),
        graph.value(node, KT.commissioningDate).toPython(),
    ) == ("Senvion", "MM92", date(2016, 4, 15))


def test_sensor_readings_traced_to_raw_files_of_every_year(graph: Graph) -> None:
    raw_files = {
        source_iri("Turbine_Data_Kelmarsh_1_2021-01-01_-_2022-01-01_228.csv"),
        source_iri("Turbine_Data_Kelmarsh_1_2022-01-01_-_2023-01-01_228.csv"),
    }

    assert raw_files <= set(graph.objects(sensor("T01", "power"), PROV.wasDerivedFrom))


def test_raw_file_is_part_of_its_own_year_archive(graph: Graph) -> None:
    raw = source_iri("Turbine_Data_Kelmarsh_1_2021-01-01_-_2022-01-01_228.csv")

    assert graph.value(raw, KT.partOf) == source_iri("Kelmarsh_SCADA_2021_4456.zip")
