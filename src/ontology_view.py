"""Render graph query results as Graphviz DOT for the ontology tab."""

import html

import pandas as pd

from src.graph_utils import PREFIXES

RDF_TYPE = str(PREFIXES["rdf"].type)
RDFS_LABEL = str(PREFIXES["rdfs"].label)
RDFS_LITERAL = str(PREFIXES["rdfs"].Literal)
SIGNAL_KEY = str(PREFIXES["kt"].signalKey)
GENERIC_TYPE = "prov:Entity"
DEFAULT_FILL = "#eceff1"
ACTIVE_ALERT_FILL = "#ef5350"
CLASS_FILLS = {
    "kt:WindFarm": "#90caf9",
    "kt:Turbine": "#90caf9",
    "kt:Rotor": "#bbdefb",
    "kt:Generator": "#bbdefb",
    "kt:Nacelle": "#bbdefb",
    "sosa:Sensor": "#c8e6c9",
    "kt:PowerModel": "#e1bee7",
    "kt:Alert": "#ffcdd2",
    "kt:SourceFile": "#fff3c4",
    "kt:Dataset": "#ffe082",
}
GRAPH_ATTRIBUTES = (
    "  rankdir=LR;\n"
    '  node [shape=plain, fontname="Helvetica", fontsize=10];\n'
    '  edge [fontname="Helvetica", fontsize=9, color="#607d8b"];\n'
)
SUBCLASS_EDGE = 'style=dashed, arrowhead=empty, label="subClassOf"'
LEGEND = [
    ("Machine & specs", "#90caf9"),
    ("Sensor (readings)", "#c8e6c9"),
    ("Power model", "#e1bee7"),
    ("Alert (red = active)", "#ffcdd2"),
    ("Source file / dataset", "#fff3c4"),
]


def qname(iri: str) -> str:
    """Compact an IRI with the project prefixes, e.g. 'kt:T01'."""
    matches = [(p, str(ns)) for p, ns in PREFIXES.items() if iri.startswith(str(ns))]
    if not matches:
        return iri
    prefix, namespace = max(matches, key=lambda m: len(m[1]))
    return f"{prefix}:{iri[len(namespace) :]}"


def dot_id(iri: str) -> str:
    """A quoted DOT node id."""
    return '"' + iri.replace("\\", "\\\\").replace('"', '\\"') + '"'


def show(value: object) -> str:
    """Readable text for a literal value."""
    return f"{value:.6g}" if isinstance(value, float) else str(value)


def html_label(title: str, kind: str, rows: list[tuple[str, str]], fill: str) -> str:
    """An HTML-like DOT label: a header cell plus one row per attribute."""
    esc = html.escape
    header = (
        f'<TR><TD COLSPAN="2" BGCOLOR="{fill}"><B>{esc(title)}</B><BR/>'
        f'<FONT POINT-SIZE="8">{esc(kind)}</FONT></TD></TR>'
    )
    body = "".join(
        f'<TR><TD ALIGN="LEFT">{esc(k)}</TD><TD ALIGN="LEFT">{esc(v)}</TD></TR>'
        for k, v in rows
    )
    return (
        '<<TABLE BORDER="0" CELLBORDER="1" CELLSPACING="0" CELLPADDING="3">'
        f"{header}{body}</TABLE>>"
    )


def main_type(types: list[str]) -> str:
    """The most specific type: prefer anything over the generic prov:Entity."""
    specific = [t for t in types if t != GENERIC_TYPE]
    return (specific or types or [""])[0]


def node_statement(
    iri: str, triples: pd.DataFrame, nodes: set[str], active: set[str]
) -> str:
    """DOT statement for one node, with its literal attributes as rows."""
    types = sorted(qname(o) for o in triples.loc[triples["p"] == RDF_TYPE, "o"])
    labels = triples.loc[triples["p"] == RDFS_LABEL, "o"].tolist()
    kind = main_type(types)
    attributes = triples[
        ~triples["p"].isin([RDF_TYPE, RDFS_LABEL])
        & ~(triples["o_is_iri"] & triples["o"].isin(nodes))
    ]
    rows = sorted(
        (qname(r.p), qname(r.o) if r.o_is_iri else show(r.o))
        for r in attributes.itertuples()
    )
    fill = ACTIVE_ALERT_FILL if iri in active else CLASS_FILLS.get(kind, DEFAULT_FILL)
    title = str(labels[0]) if labels else qname(iri)
    return f"  {dot_id(iri)} [label={html_label(title, kind, rows, fill)}];"


def edge_statements(triples: pd.DataFrame, nodes: set[str]) -> list[str]:
    """DOT edges for relations between nodes of the subgraph."""
    links = triples[
        triples["o_is_iri"] & triples["o"].isin(nodes) & (triples["p"] != RDF_TYPE)
    ]
    return sorted(
        f'  {dot_id(r.s)} -> {dot_id(r.o)} [label="{qname(r.p)}"];'
        for r in links.itertuples()
    )


def legend_statement() -> str:
    """A small colour legend node."""
    rows = "".join(
        f'<TR><TD BGCOLOR="{fill}">{html.escape(text)}</TD></TR>'
        for text, fill in LEGEND
    )
    table = f'<<TABLE BORDER="0" CELLBORDER="1" CELLSPACING="0">{rows}</TABLE>>'
    return f"  legend [label={table}];"


def without_sensors(triples: pd.DataFrame, keep: set[str]) -> pd.DataFrame:
    """Drop sensors whose signal key is not in keep, with their links."""
    keys = triples[triples["p"] == SIGNAL_KEY]
    dropped = set(keys.loc[~keys["o"].astype(str).isin(keep), "s"])
    return triples[~triples["s"].isin(dropped) & ~triples["o"].isin(dropped)]


def lineage_dot(triples: pd.DataFrame, active_alerts: set[str]) -> str:
    """DOT for a turbine's lineage subgraph (rows from graph_utils.get_lineage)."""
    nodes = set(triples["s"])
    statements = [
        node_statement(iri, triples[triples["s"] == iri], nodes, active_alerts)
        for iri in sorted(nodes)
    ]
    body = "\n".join(
        [*statements, *edge_statements(triples, nodes), legend_statement()]
    )
    return f"digraph lineage {{\n{GRAPH_ATTRIBUTES}{body}\n}}\n"


def schema_dot(classes: pd.DataFrame, properties: pd.DataFrame) -> str:
    """DOT class diagram from graph_utils.get_schema results."""
    literal = properties["range"] == RDFS_LITERAL
    relations = properties[~literal]
    referenced = set(relations["domain"]) | set(relations["range"])
    all_classes = sorted(
        set(classes["class"]) | set(classes["parent"].dropna()) | referenced
    )
    statements = []
    for cls in all_classes:
        rows = sorted(
            ("", qname(p))
            for p in properties.loc[literal & (properties["domain"] == cls), "property"]
        )
        kind = "class" if cls in set(classes["class"]) else "external class"
        fill = CLASS_FILLS.get(qname(cls), DEFAULT_FILL)
        statements.append(
            f"  {dot_id(cls)} [label={html_label(qname(cls), kind, rows, fill)}];"
        )
    edges = [
        f'  {dot_id(r.domain)} -> {dot_id(r.range)} [label="{qname(r.property)}"];'
        for r in relations.itertuples()
    ] + [
        f"  {dot_id(r.cls)} -> {dot_id(r.parent)} [{SUBCLASS_EDGE}];"
        for r in classes.rename(columns={"class": "cls"})
        .dropna(subset=["parent"])
        .itertuples()
    ]
    body = "\n".join([*statements, *sorted(edges)])
    return f"digraph schema {{\n{GRAPH_ATTRIBUTES}{body}\n}}\n"
