# Kelmarsh Wind Farm Digital Twin (PoC)

A one-day proof of concept of a data-driven digital twin for the Kelmarsh wind
farm (UK, 6 x Senvion MM92, 12.3 MW). It loads and cleans 2022 SCADA data,
describes the farm in an RDF ontology, trains one LightGBM power model per
turbine, raises underperformance alerts, and replays everything in a Streamlit
dashboard. See [docs/spec.md](docs/spec.md) for the full specification.

## Setup

Install [uv](https://docs.astral.sh/uv/), then:

```bash
make setup        # uv sync
```

## Run

```bash
make download     # fetch raw data into data/raw/ (MD5-verified, skips existing)
make inspect      # print raw file structure and column names
make data         # load_scada + clean
make ontology     # build ontology/kelmarsh.ttl
make train        # one power model per turbine
make alerts       # underperformance alerts
make app          # Streamlit dashboard
make all          # download through alerts
```

Every script also runs standalone: `uv run python -m src.<name>`.

## Testing and linting

```bash
make test         # uv run pytest
make lint         # uv run ruff check .
```

## Known limitations

- One year (2022) only.
- Simple cleaning rules (spec §7.4): a derating plateau at about 1,650 kW above
  rated wind speed is not removed, because the pitch rule only applies below
  rated wind speed.
- No validation of alerts against the status/event logs.

## Attribution

Kelmarsh wind farm data by Cubico Sustainable Investments Ltd, licensed under
CC-BY-4.0. DOI: [10.5281/zenodo.16807551](https://doi.org/10.5281/zenodo.16807551).

## Deviations from spec

- `config.yaml` additionally holds the download URLs/MD5s, the sample interval,
  the rated wind speed (12 m/s) and the standard pressure, so no values are
  hard-coded in scripts.
- `matplotlib` is added (not in spec §4) to save the power curve PNGs.
- `pytest` and `ruff` are added as dev dependencies.
- The SCADA archive holds 6 `Turbine_Data_Kelmarsh_<N>_…csv` files and
  6 `Status_Kelmarsh_<N>_…csv` files (status/event logs, not used). In the
  turbine files the column header is itself a comment line
  (`# Date and time,…`) after 9 metadata lines, so the header is detected as
  the last `#` line before the data. The files have 303 columns and CRLF line
  endings; the static CSV has a UTF-8 BOM.
- The 7 signal column names guessed in spec §6 were all confirmed exactly.
- The mapping CSV's `Greenbyte Title` is the column name without the unit
  suffix (e.g. `Ambient temperature (converter)`), so signals are matched to
  it by stripping the unit.
- `config.yaml` gained a `model` section (`inputs: [wind_speed,
  wind_direction, ambient_temp]`, `target: power`). The model's sensor inputs
  are these three signals; `air_density` and the sin/cos of wind direction
  are derived from them, so they are not sensors in the graph.
- Ontology extensions beyond spec §7.5: `kt:turbineId` (e.g. `"T01"`, used
  by every SPARQL lookup), and `kt:manufacturerTitle` / `kt:greenbyteSignalId`
  on sensors, filled from the mapping CSV where a match exists (all 7 signals
  match). Observable properties (`kt:WindSpeed`, …) are typed
  `sosa:ObservableProperty`; units use QUDT (`unit:M-PER-SEC`, `unit:KiloW`,
  `unit:DEG`, `unit:DEG_C`, `unit:REV-PER-MIN`). `nacelle_direction` is
  attached to the Nacelle (not specified in the spec).
- The mapping CSV lists the unit of `Power` as `kWh`; the SCADA column is
  `Power (kW)` (10-minute mean power), so the sensor unit is `unit:KiloW`.
- `build_ontology.py` already creates one `kt:PowerModel` per turbine with
  its inputs and target (from `config.yaml`), so `train.py` can read the model
  inputs from the graph. `train.py` replaces each node with the trained
  version (metrics, `prov:generatedAtTime`).
- The schema is written first in `ontology/kelmarsh.ttl` by `save_graph`,
  which serialises schema triples and instance triples as two Turtle blocks.
