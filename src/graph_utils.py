"""The single access point to the Kelmarsh RDF graph.

Lookups use SPARQL so that structure comes from the graph, not from config.
"""

from datetime import datetime
from decimal import Decimal
from pathlib import Path

import pandas as pd
from rdflib import RDF, RDFS, XSD, Graph, Literal, Namespace, URIRef
from rdflib.query import Result

KT = Namespace("https://example.org/kelmarsh-twin#")
SOSA = Namespace("http://www.w3.org/ns/sosa/")
PROV = Namespace("http://www.w3.org/ns/prov#")
QUDT = Namespace("http://qudt.org/schema/qudt/")
UNIT = Namespace("http://qudt.org/vocab/unit/")
GEO = Namespace("http://www.w3.org/2003/01/geo/wgs84_pos#")
PREFIXES = {
    "kt": KT,
    "sosa": SOSA,
    "prov": PROV,
    "qudt": QUDT,
    "unit": UNIT,
    "geo": GEO,
    "rdfs": RDFS,
    "xsd": XSD,
}
SCHEMA_TYPES = {RDFS.Class, RDF.Property}

TURBINES_QUERY = """
SELECT ?turbine_id ?label ?lat ?long ?rated_power_kw ?rotor_diameter_m
       ?hub_height_m
WHERE {
  ?farm kt:hasTurbine ?turbine .
  ?turbine kt:turbineId ?turbine_id ;
           rdfs:label ?label ;
           geo:lat ?lat ;
           geo:long ?long ;
           kt:ratedPowerKW ?rated_power_kw ;
           kt:rotorDiameterM ?rotor_diameter_m ;
           kt:hubHeightM ?hub_height_m .
}
ORDER BY ?turbine_id
"""

SENSORS_QUERY = """
SELECT ?signal_key ?scada_column ?unit ?parquet_path ?component ?observes
WHERE {
  ?turbine kt:turbineId ?turbine_id ;
           kt:hasSensor ?sensor .
  ?sensor kt:signalKey ?signal_key ;
          kt:scadaColumn ?scada_column ;
          qudt:unit ?unit ;
          kt:storedIn ?parquet_path ;
          sosa:observes ?observes ;
          kt:attachedTo ?part .
  ?part a ?component .
  ?component rdfs:subClassOf kt:Component .
}
ORDER BY ?signal_key
"""

MODEL_INPUTS_QUERY = """
SELECT ?signal_key
WHERE {
  ?model kt:forTurbine ?turbine ;
         kt:usesInput ?sensor .
  ?turbine kt:turbineId ?turbine_id .
  ?sensor kt:signalKey ?signal_key .
}
ORDER BY ?signal_key
"""

MODEL_TARGET_QUERY = """
SELECT ?signal_key
WHERE {
  ?model kt:forTurbine ?turbine ;
         kt:target ?sensor .
  ?turbine kt:turbineId ?turbine_id .
  ?sensor kt:signalKey ?signal_key .
}
"""

ALERTS_QUERY = """
SELECT ?alert ?turbine_id ?model ?start ?end ?mean_residual_fraction
       ?lost_energy_mwh
WHERE {
  ?alert a kt:Alert ;
         kt:concerns ?turbine ;
         kt:raisedBy ?model ;
         kt:startTime ?start ;
         kt:endTime ?end ;
         kt:meanResidualFraction ?mean_residual_fraction ;
         kt:lostEnergyMWh ?lost_energy_mwh .
  ?turbine kt:turbineId ?turbine_id .
}
ORDER BY ?turbine_id ?start
"""


def turbine_iri(turbine_id: str) -> URIRef:
    """IRI of a turbine, e.g. kt:T01."""
    return KT[turbine_id]


def component_iri(turbine_id: str, component: str) -> URIRef:
    """IRI of a turbine component, e.g. kt:T01_Rotor."""
    return KT[f"{turbine_id}_{component}"]


def sensor_iri(turbine_id: str, signal_key: str) -> URIRef:
    """IRI of a turbine sensor, e.g. kt:T01_power."""
    return KT[f"{turbine_id}_{signal_key}"]


def model_iri(turbine_id: str) -> URIRef:
    """IRI of the power model of a turbine, e.g. kt:PowerModel_T01."""
    return KT[f"PowerModel_{turbine_id}"]


def alert_iri(turbine_id: str, number: int) -> URIRef:
    """IRI of an alert, e.g. kt:Alert_T01_001."""
    return KT[f"Alert_{turbine_id}_{number:03d}"]


def decimal(value: float) -> Literal:
    """An xsd:decimal literal."""
    return Literal(Decimal(str(value)), datatype=XSD.decimal)


def datetime_literal(value: datetime) -> Literal:
    """An xsd:dateTime literal from a datetime or pandas Timestamp."""
    return Literal(pd.Timestamp(value).to_pydatetime(), datatype=XSD.dateTime)


def new_graph() -> Graph:
    """An empty graph with the project prefixes bound (overriding defaults)."""
    g = Graph()
    for prefix, namespace in PREFIXES.items():
        g.bind(prefix, namespace, override=True, replace=True)
    return g


def load_graph(path: Path | str) -> Graph:
    """Parse a Turtle file into a graph with the project prefixes bound."""
    g = new_graph()
    g.parse(Path(path), format="turtle")
    return g


def save_graph(g: Graph, path: Path | str) -> None:
    """Write the graph as Turtle with the schema block first."""
    schema_subjects = {s for s, o in g.subject_objects(RDF.type) if o in SCHEMA_TYPES}
    schema, data = new_graph(), new_graph()
    for triple in g:
        (schema if triple[0] in schema_subjects else data).add(triple)
    text = (
        "# Schema\n"
        + schema.serialize(format="turtle")
        + "\n# Instances\n"
        + data.serialize(format="turtle")
    )
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(text, encoding="utf-8")


def to_python(term: object) -> object:
    """Convert an rdflib term to a plain Python value."""
    value = term.toPython() if term is not None else None
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, URIRef):
        return str(value)
    return value


def result_frame(result: Result) -> pd.DataFrame:
    """Turn a SPARQL SELECT result into a DataFrame."""
    columns = [str(v) for v in result.vars]
    rows = [[to_python(term) for term in row] for row in result]
    return pd.DataFrame(rows, columns=columns)


def query(g: Graph, sparql: str, **bindings: str) -> pd.DataFrame:
    """Run a SELECT query with plain-literal bindings, return a DataFrame."""
    init = {name: Literal(value) for name, value in bindings.items()}
    return result_frame(g.query(sparql, initNs=PREFIXES, initBindings=init))


def get_turbines(g: Graph) -> pd.DataFrame:
    """Turbines with id, label, coordinates, rated power and dimensions."""
    return query(g, TURBINES_QUERY)


def get_sensors(g: Graph, turbine_id: str) -> pd.DataFrame:
    """Sensors of one turbine: signal key, SCADA column, unit, Parquet path."""
    return query(g, SENSORS_QUERY, turbine_id=turbine_id).assign(turbine_id=turbine_id)


def get_model_inputs(g: Graph, turbine_id: str) -> list[str]:
    """Signal keys of the sensors the turbine's power model uses as inputs."""
    return query(g, MODEL_INPUTS_QUERY, turbine_id=turbine_id)["signal_key"].tolist()


def get_model_target(g: Graph, turbine_id: str) -> str:
    """Signal key of the sensor the turbine's power model predicts."""
    keys = query(g, MODEL_TARGET_QUERY, turbine_id=turbine_id)["signal_key"]
    if len(keys) != 1:
        raise LookupError(
            f"Expected one model target for {turbine_id}, got {len(keys)}"
        )
    return keys.iloc[0]


def get_alerts(g: Graph, turbine_id: str | None = None) -> pd.DataFrame:
    """Alerts, optionally for one turbine, with UTC start and end times."""
    bindings = {} if turbine_id is None else {"turbine_id": turbine_id}
    frame = query(g, ALERTS_QUERY, **bindings)
    return frame.assign(
        turbine_id=frame["turbine_id"] if turbine_id is None else turbine_id,
        start=pd.to_datetime(frame["start"], utc=True),
        end=pd.to_datetime(frame["end"], utc=True),
    )


def add_model(
    g: Graph,
    turbine_id: str,
    inputs: list[str],
    target: str,
    metrics: dict[str, float] | None = None,
    generated_at: datetime | None = None,
) -> URIRef:
    """Add (or replace) the power model node of a turbine."""
    model = model_iri(turbine_id)
    g.remove((model, None, None))
    g.add((model, RDF.type, KT.PowerModel))
    g.add((model, RDF.type, PROV.Entity))
    g.add((model, RDFS.label, Literal(f"Power model {turbine_id}")))
    g.add((model, KT.forTurbine, turbine_iri(turbine_id)))
    g.add((model, KT.target, sensor_iri(turbine_id, target)))
    for key in inputs:
        g.add((model, KT.usesInput, sensor_iri(turbine_id, key)))
    if metrics is not None:
        g.add((model, KT.maeKW, decimal(metrics["mae_kw"])))
        g.add((model, KT.nmae, decimal(metrics["nmae"])))
    if generated_at is not None:
        g.add((model, PROV.generatedAtTime, datetime_literal(generated_at)))
    return model


def remove_alerts(g: Graph, turbine_id: str) -> int:
    """Remove all alerts of a turbine; return how many were removed."""
    alerts = get_alerts(g, turbine_id)["alert"]
    for alert in alerts:
        g.remove((URIRef(alert), None, None))
    return len(alerts)


def add_alert(
    g: Graph,
    turbine_id: str,
    number: int,
    start: datetime,
    end: datetime,
    mean_residual_fraction: float,
    lost_energy_mwh: float,
) -> URIRef:
    """Add an underperformance alert linked to its turbine and power model."""
    alert = alert_iri(turbine_id, number)
    g.add((alert, RDF.type, KT.Alert))
    g.add((alert, RDFS.label, Literal(f"Alert {number} {turbine_id}")))
    g.add((alert, KT.concerns, turbine_iri(turbine_id)))
    g.add((alert, KT.raisedBy, model_iri(turbine_id)))
    g.add((alert, KT.startTime, datetime_literal(start)))
    g.add((alert, KT.endTime, datetime_literal(end)))
    g.add((alert, KT.meanResidualFraction, decimal(mean_residual_fraction)))
    g.add((alert, KT.lostEnergyMWh, decimal(lost_energy_mwh)))
    return alert
