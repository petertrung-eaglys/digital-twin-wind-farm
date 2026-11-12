"""Shared fixtures: a small synthetic Kelmarsh graph."""

import pandas as pd
import pytest
from rdflib import Graph

from src.build_ontology import build_graph

SIGNALS = {
    "wind_speed": "Wind speed (m/s)",
    "power": "Power (kW)",
    "wind_direction": "Wind direction (°)",
    "nacelle_direction": "Nacelle position (°)",
    "ambient_temp": "Ambient temperature (converter) (°C)",
    "pitch": "Blade angle (pitch position) A (°)",
    "rotor_speed": "Rotor speed (RPM)",
}
CONFIG = {
    "paths": {"processed": "data/processed"},
    "signals": SIGNALS,
    "model": {
        "inputs": ["wind_speed", "wind_direction", "ambient_temp"],
        "target": "power",
    },
}


def static_row(number: int, lat: float, hub: float) -> dict:
    return {
        "Wind Farm": "Kelmarsh",
        "Title": f"Kelmarsh {number}",
        "Rated power (kW)": 2050,
        "Hub Height (m)": hub,
        "Rotor Diameter (m)": 92,
        "Latitude": lat,
        "Longitude": -0.94,
    }


@pytest.fixture
def static() -> pd.DataFrame:
    return pd.DataFrame([static_row(1, 52.40, 78.5), static_row(2, 52.41, 68.5)])


@pytest.fixture
def mapping() -> pd.DataFrame:
    """Mapping without an entry for rotor speed."""
    return pd.DataFrame(
        [
            {
                "Greenbyte Signal ID": 5,
                "Greenbyte Title": "Power",
                "Manufacturer Title": "Actual value of active power",
                "Unit": "kWh",
            },
            {
                "Greenbyte Signal ID": 359,
                "Greenbyte Title": "Ambient temperature (converter)",
                "Manufacturer Title": "Temperature of converter inlet air",
                "Unit": "degC",
            },
        ]
    )


@pytest.fixture
def graph(static: pd.DataFrame, mapping: pd.DataFrame) -> Graph:
    return build_graph(static, mapping, CONFIG)
