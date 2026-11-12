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
DOWNLOADS = {
    "scada_dir": "scada_2022",
    "files": [
        {"name": n, "url": f"https://zenodo.org/{n}", "md5": "0" * 32}
        for n in (
            "Kelmarsh_WT_static.csv",
            "Kelmarsh_WT_dataSignalMapping.csv",
            "Kelmarsh_SCADA_2022_4457.zip",
        )
    ],
}
DATASET = {
    "title": "Kelmarsh wind farm data",
    "doi": "10.5281/zenodo.16807551",
    "publisher": "Cubico Sustainable Investments Ltd",
    "license": "CC-BY-4.0",
}
TURBINE_FILES = {
    "T01": "Turbine_Data_Kelmarsh_1_2022-01-01_-_2023-01-01_228.csv",
    "T02": "Turbine_Data_Kelmarsh_2_2022-01-01_-_2023-01-01_229.csv",
}
CONFIG = {
    "paths": {"processed": "data/processed"},
    "dataset": DATASET,
    "downloads": DOWNLOADS,
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
        "Manufacturer": "Senvion",
        "Model": "MM92",
        "Commercial Operations Date": "15/04/2016",
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
    return build_graph(static, mapping, CONFIG, TURBINE_FILES)
