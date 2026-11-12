"""Build the Kelmarsh RDF graph (schema, sources, farm, turbines, sensors, models)."""

import logging
import re
from datetime import datetime
from pathlib import Path

import pandas as pd
from rdflib import RDF, RDFS, XSD, Graph, Literal, URIRef

from src.config import load_config
from src.graph_utils import (
    DATASET_IRI,
    GEO,
    KT,
    PROV,
    QUDT,
    SOSA,
    UNIT,
    add_model,
    component_iri,
    decimal,
    new_graph,
    save_graph,
    sensor_iri,
    source_iri,
    turbine_iri,
)
from src.scada_format import format_turbine_id, turbine_id_from_filename

logger = logging.getLogger(__name__)

STATIC_FILE = "Kelmarsh_WT_static.csv"
MAPPING_FILE = "Kelmarsh_WT_dataSignalMapping.csv"
UNIT_SUFFIX = re.compile(r"\s*\([^()]*\)$")
TURBINE_NUMBER_IN_TITLE = re.compile(r"(\d+)$")
COMPONENTS = ["Rotor", "Generator", "Nacelle"]
TURBINE_FILE_GLOB = "Turbine_Data_*.csv"
STATIC_DATE_FORMAT = "%d/%m/%Y"

# signal key -> (component, observable property, QUDT unit)
SIGNAL_SEMANTICS: dict[str, tuple[str, str, URIRef]] = {
    "wind_speed": ("Nacelle", "WindSpeed", UNIT["M-PER-SEC"]),
    "wind_direction": ("Nacelle", "WindDirection", UNIT.DEG),
    "nacelle_direction": ("Nacelle", "NacelleDirection", UNIT.DEG),
    "ambient_temp": ("Nacelle", "AmbientTemperature", UNIT.DEG_C),
    "pitch": ("Rotor", "PitchAngle", UNIT.DEG),
    "rotor_speed": ("Rotor", "RotorSpeed", UNIT["REV-PER-MIN"]),
    "power": ("Generator", "ActivePower", UNIT.KiloW),
}

# (class, superclass or None, label, comment)
CLASSES: list[tuple[URIRef, URIRef | None, str, str]] = [
    (KT.WindFarm, None, "Wind farm", "A wind farm site, here Kelmarsh."),
    (KT.Turbine, None, "Turbine", "One wind turbine."),
    (KT.Component, None, "Component", "Superclass for turbine parts."),
    (KT.Rotor, KT.Component, "Rotor", "The rotor with hub and blades."),
    (KT.Generator, KT.Component, "Generator", "The electrical generator."),
    (KT.Nacelle, KT.Component, "Nacelle", "The nacelle housing on the tower."),
    (SOSA.Sensor, None, "Sensor", "One SCADA signal of a turbine."),
    (
        KT.PowerModel,
        PROV.Entity,
        "Power model",
        "A trained model that predicts turbine power.",
    ),
    (KT.Alert, None, "Alert", "An underperformance alert period."),
    (
        KT.Dataset,
        PROV.Entity,
        "Dataset",
        "The published dataset all raw files come from.",
    ),
    (
        KT.SourceFile,
        PROV.Entity,
        "Source file",
        "A raw file of the dataset that graph facts or readings come from.",
    ),
]

# (property, domain, range, label, comment)
PROPERTIES: list[tuple[URIRef, URIRef, URIRef, str, str]] = [
    (KT.hasTurbine, KT.WindFarm, KT.Turbine, "has turbine", "A turbine of the farm."),
    (KT.hasComponent, KT.Turbine, KT.Component, "has component", "A turbine part."),
    (KT.hasSensor, KT.Turbine, SOSA.Sensor, "has sensor", "A turbine's sensor."),
    (KT.attachedTo, SOSA.Sensor, KT.Component, "attached to", "Sensor location."),
    (
        SOSA.observes,
        SOSA.Sensor,
        SOSA.ObservableProperty,
        "observes",
        "The property the sensor measures.",
    ),
    (QUDT.unit, SOSA.Sensor, QUDT.Unit, "unit", "QUDT unit of the signal."),
    (
        KT.signalKey,
        SOSA.Sensor,
        RDFS.Literal,
        "signal key",
        "Config key and Parquet column name, e.g. power.",
    ),
    (
        KT.scadaColumn,
        SOSA.Sensor,
        RDFS.Literal,
        "SCADA column",
        "Original column name in the SCADA export.",
    ),
    (
        KT.storedIn,
        SOSA.Sensor,
        RDFS.Literal,
        "stored in",
        "Path of the Parquet file holding the time series.",
    ),
    (
        KT.manufacturerTitle,
        SOSA.Sensor,
        RDFS.Literal,
        "manufacturer title",
        "Manufacturer signal name from the signal mapping file.",
    ),
    (
        KT.greenbyteSignalId,
        SOSA.Sensor,
        RDFS.Literal,
        "Greenbyte signal id",
        "Signal id from the signal mapping file.",
    ),
    (KT.turbineId, KT.Turbine, RDFS.Literal, "turbine id", "Short id, e.g. T01."),
    (KT.ratedPowerKW, KT.Turbine, RDFS.Literal, "rated power (kW)", "Rated power."),
    (KT.rotorDiameterM, KT.Turbine, RDFS.Literal, "rotor diameter (m)", "Diameter."),
    (KT.hubHeightM, KT.Turbine, RDFS.Literal, "hub height (m)", "Hub height."),
    (GEO.lat, KT.Turbine, RDFS.Literal, "latitude", "WGS84 latitude."),
    (GEO.long, KT.Turbine, RDFS.Literal, "longitude", "WGS84 longitude."),
    (KT.forTurbine, KT.PowerModel, KT.Turbine, "for turbine", "Modelled turbine."),
    (KT.usesInput, KT.PowerModel, SOSA.Sensor, "uses input", "An input signal."),
    (KT.target, KT.PowerModel, SOSA.Sensor, "target", "The predicted signal."),
    (KT.maeKW, KT.PowerModel, RDFS.Literal, "MAE (kW)", "Test mean abs. error."),
    (KT.nmae, KT.PowerModel, RDFS.Literal, "nMAE", "MAE / rated power."),
    (KT.raisedBy, KT.Alert, KT.PowerModel, "raised by", "Model behind the alert."),
    (KT.concerns, KT.Alert, KT.Turbine, "concerns", "Turbine of the alert."),
    (KT.startTime, KT.Alert, RDFS.Literal, "start time", "Alert start (UTC)."),
    (KT.endTime, KT.Alert, RDFS.Literal, "end time", "Alert end (UTC)."),
    (
        KT.meanResidualFraction,
        KT.Alert,
        RDFS.Literal,
        "mean residual fraction",
        "Mean of (power - expected) / rated power in the period.",
    ),
    (
        KT.lostEnergyMWh,
        KT.Alert,
        RDFS.Literal,
        "lost energy (MWh)",
        "Sum of expected minus actual energy in the period.",
    ),
    (KT.manufacturer, KT.Turbine, RDFS.Literal, "manufacturer", "Maker."),
    (KT.turbineModel, KT.Turbine, RDFS.Literal, "turbine model", "Model name."),
    (
        KT.commissioningDate,
        KT.Turbine,
        RDFS.Literal,
        "commissioning date",
        "Commercial operations date.",
    ),
    (
        KT.modelFile,
        KT.PowerModel,
        RDFS.Literal,
        "model file",
        "Path of the saved LightGBM model.",
    ),
    (
        PROV.wasDerivedFrom,
        PROV.Entity,
        PROV.Entity,
        "was derived from",
        "The source file a turbine's specs or a sensor's readings come from.",
    ),
    (
        KT.partOf,
        KT.SourceFile,
        PROV.Entity,
        "part of",
        "The archive or dataset that contains the file.",
    ),
    (KT.fileName, KT.SourceFile, RDFS.Literal, "file name", "Raw file name."),
    (KT.downloadUrl, KT.SourceFile, RDFS.Literal, "download URL", "Zenodo URL."),
    (KT.md5, KT.SourceFile, RDFS.Literal, "MD5", "Checksum of the file."),
    (KT.doi, KT.Dataset, RDFS.Literal, "DOI", "Digital object identifier."),
    (KT.publisher, KT.Dataset, RDFS.Literal, "publisher", "Data owner."),
    (KT.license, KT.Dataset, RDFS.Literal, "license", "Dataset license."),
]


def add_schema(g: Graph) -> None:
    """Add classes and properties with labels and comments."""
    for cls, parent, label, comment in CLASSES:
        g.add((cls, RDF.type, RDFS.Class))
        g.add((cls, RDFS.label, Literal(label)))
        g.add((cls, RDFS.comment, Literal(comment)))
        if parent is not None:
            g.add((cls, RDFS.subClassOf, parent))
    for prop, domain, range_, label, comment in PROPERTIES:
        g.add((prop, RDF.type, RDF.Property))
        g.add((prop, RDFS.domain, domain))
        g.add((prop, RDFS.range, range_))
        g.add((prop, RDFS.label, Literal(label)))
        g.add((prop, RDFS.comment, Literal(comment)))


def strip_unit(column: str) -> str:
    """Drop a trailing '(unit)' from a SCADA column name."""
    return UNIT_SUFFIX.sub("", column)


def turbine_id_from_title(title: str) -> str:
    """Derive the turbine id from a static-file title like 'Kelmarsh 3'."""
    match = TURBINE_NUMBER_IN_TITLE.search(title.strip())
    if match is None:
        raise ValueError(f"No turbine number in title: {title}")
    return format_turbine_id(int(match.group(1)))


def turbines_from_static(static: pd.DataFrame) -> list[dict]:
    """One record per turbine with id, label, coordinates and dimensions."""
    return [
        {
            "farm": row["Wind Farm"],
            "turbine_id": turbine_id_from_title(row["Title"]),
            "label": row["Title"],
            "lat": row["Latitude"],
            "long": row["Longitude"],
            "rated_power_kw": row["Rated power (kW)"],
            "rotor_diameter_m": row["Rotor Diameter (m)"],
            "hub_height_m": row["Hub Height (m)"],
            "manufacturer": row["Manufacturer"],
            "model": row["Model"],
            "commissioned": datetime.strptime(
                row["Commercial Operations Date"], STATIC_DATE_FORMAT
            ).date(),
        }
        for _, row in static.iterrows()
    ]


def mapping_entry(mapping: pd.DataFrame, column: str) -> dict | None:
    """The mapping row whose Greenbyte title matches the column, if any."""
    hits = mapping[mapping["Greenbyte Title"] == strip_unit(column)]
    return None if hits.empty else hits.iloc[0].to_dict()


def add_dataset(g: Graph, dataset: dict) -> None:
    """Add the published dataset node."""
    g.add((DATASET_IRI, RDF.type, KT.Dataset))
    g.add((DATASET_IRI, RDF.type, PROV.Entity))
    g.add((DATASET_IRI, RDFS.label, Literal(dataset["title"])))
    g.add((DATASET_IRI, KT.doi, Literal(dataset["doi"])))
    g.add((DATASET_IRI, KT.publisher, Literal(dataset["publisher"])))
    g.add((DATASET_IRI, KT.license, Literal(dataset["license"])))


def add_source_file(g: Graph, name: str, part_of: URIRef, **details: str) -> URIRef:
    """Add a raw source file (optional download URL and MD5) and its container."""
    node = source_iri(name)
    g.add((node, RDF.type, KT.SourceFile))
    g.add((node, RDF.type, PROV.Entity))
    g.add((node, RDFS.label, Literal(name)))
    g.add((node, KT.fileName, Literal(name)))
    g.add((node, KT.partOf, part_of))
    for key, prop in [("url", KT.downloadUrl), ("md5", KT.md5)]:
        if key in details:
            g.add((node, prop, Literal(details[key])))
    return node


def add_sources(g: Graph, config: dict, turbine_files: dict[str, str]) -> None:
    """Add the dataset, the downloaded files and the per-turbine SCADA files."""
    add_dataset(g, config["dataset"])
    for f in config["downloads"]["files"]:
        add_source_file(g, f["name"], DATASET_IRI, url=f["url"], md5=f["md5"])
    archive = next(
        f["name"] for f in config["downloads"]["files"] if f["name"].endswith(".zip")
    )
    for name in turbine_files.values():
        add_source_file(g, name, source_iri(archive))


def add_turbine(g: Graph, farm: URIRef, turbine: dict) -> None:
    """Add a turbine with its specs, their source and its components."""
    tid = turbine["turbine_id"]
    node = turbine_iri(tid)
    g.add((farm, KT.hasTurbine, node))
    g.add((node, RDF.type, KT.Turbine))
    g.add((node, KT.turbineId, Literal(tid)))
    g.add((node, RDFS.label, Literal(turbine["label"])))
    g.add((node, GEO.lat, decimal(turbine["lat"])))
    g.add((node, GEO.long, decimal(turbine["long"])))
    g.add((node, KT.ratedPowerKW, decimal(turbine["rated_power_kw"])))
    g.add((node, KT.rotorDiameterM, decimal(turbine["rotor_diameter_m"])))
    g.add((node, KT.hubHeightM, decimal(turbine["hub_height_m"])))
    g.add((node, KT.manufacturer, Literal(turbine["manufacturer"])))
    g.add((node, KT.turbineModel, Literal(turbine["model"])))
    g.add(
        (
            node,
            KT.commissioningDate,
            Literal(turbine["commissioned"], datatype=XSD.date),
        )
    )
    g.add((node, PROV.wasDerivedFrom, source_iri(STATIC_FILE)))
    for component in COMPONENTS:
        part = component_iri(tid, component)
        g.add((node, KT.hasComponent, part))
        g.add((part, RDF.type, KT[component]))
        g.add((part, RDFS.label, Literal(f"{component} {tid}")))


def add_sensor(
    g: Graph,
    turbine_id: str,
    key: str,
    column: str,
    parquet_path: str,
    mapping: pd.DataFrame,
    raw_file: str,
) -> None:
    """Add one sensor of a turbine, attached to its component, with sources."""
    component, observable, unit = SIGNAL_SEMANTICS[key]
    sensor = sensor_iri(turbine_id, key)
    g.add((turbine_iri(turbine_id), KT.hasSensor, sensor))
    g.add((sensor, RDF.type, SOSA.Sensor))
    g.add((sensor, RDFS.label, Literal(f"{key} {turbine_id}")))
    g.add((sensor, KT.attachedTo, component_iri(turbine_id, component)))
    g.add((sensor, SOSA.observes, KT[observable]))
    g.add((sensor, QUDT.unit, unit))
    g.add((sensor, KT.signalKey, Literal(key)))
    g.add((sensor, KT.scadaColumn, Literal(column)))
    g.add((sensor, KT.storedIn, Literal(parquet_path)))
    g.add((sensor, PROV.wasDerivedFrom, source_iri(raw_file)))
    entry = mapping_entry(mapping, column)
    if entry is not None:
        g.add((sensor, PROV.wasDerivedFrom, source_iri(MAPPING_FILE)))
        g.add((sensor, KT.manufacturerTitle, Literal(entry["Manufacturer Title"])))
        g.add(
            (sensor, KT.greenbyteSignalId, Literal(int(entry["Greenbyte Signal ID"])))
        )


def add_observable_properties(g: Graph) -> None:
    """Declare the observable properties the sensors observe."""
    for _, observable, _ in SIGNAL_SEMANTICS.values():
        g.add((KT[observable], RDF.type, SOSA.ObservableProperty))
        g.add((KT[observable], RDFS.label, Literal(observable)))


def turbine_files_in(scada_dir: Path) -> dict[str, str]:
    """Map turbine id to its raw SCADA file name."""
    return {
        turbine_id_from_filename(p.name): p.name
        for p in sorted(scada_dir.glob(TURBINE_FILE_GLOB))
    }


def build_graph(
    static: pd.DataFrame,
    mapping: pd.DataFrame,
    config: dict,
    turbine_files: dict[str, str],
) -> Graph:
    """Build the full graph from the static and mapping tables and the config."""
    g = new_graph()
    add_schema(g)
    add_observable_properties(g)
    add_sources(g, config, turbine_files)
    processed = Path(config["paths"]["processed"])
    for turbine in turbines_from_static(static):
        farm = KT[turbine["farm"]]
        g.add((farm, RDF.type, KT.WindFarm))
        g.add((farm, RDFS.label, Literal(turbine["farm"])))
        add_turbine(g, farm, turbine)
        tid = turbine["turbine_id"]
        parquet = str(processed / f"scada_{tid}.parquet")
        for key, column in config["signals"].items():
            add_sensor(g, tid, key, column, parquet, mapping, turbine_files[tid])
        add_model(g, tid, config["model"]["inputs"], config["model"]["target"])
    return g


def main() -> None:
    """Build the graph from data/raw and write it to the ontology path."""
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    config = load_config()
    raw = Path(config["paths"]["raw"])
    static = pd.read_csv(raw / STATIC_FILE, encoding="utf-8-sig")
    mapping = pd.read_csv(raw / MAPPING_FILE, encoding="utf-8-sig")
    turbine_files = turbine_files_in(raw / config["downloads"]["scada_dir"])
    g = build_graph(static, mapping, config, turbine_files)
    save_graph(g, config["paths"]["ontology"])
    logger.info("Wrote %d triples to %s", len(g), config["paths"]["ontology"])


if __name__ == "__main__":
    main()
