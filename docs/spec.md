# Kelmarsh Wind Farm Digital Twin PoC: Specification

## 1. Goal

Build a one-day proof of concept of a data-driven digital twin for Kelmarsh wind farm (UK, 6 x Senvion MM92, 12.3 MW). The PoC must show the full chain in one working demo:

1. Load and clean real SCADA data.
2. Describe the farm, turbines, components and signals in an RDF ontology.
3. Train a power performance model per turbine.
4. Compare expected and actual power, and raise underperformance alerts.
5. Store alerts in the ontology, linked to turbines and models.
6. Show everything in a Streamlit dashboard that replays historical data as if it were live.

The PoC favours a working end-to-end slice over accuracy or completeness.

## 2. Data source

Dataset: Kelmarsh wind farm data, Zenodo record 16807551, DOI 10.5281/zenodo.16807551.
License: CC-BY-4.0. Attribution to Cubico Sustainable Investments Ltd must appear in the README and in the dashboard footer.

Files used in this PoC:

| File | URL | MD5 |
|---|---|---|
| `Kelmarsh_WT_static.csv` | https://zenodo.org/records/16807551/files/Kelmarsh_WT_static.csv?download=1 | af3a038f0f7fddfc1608ad0bfc8cf5ba |
| `Kelmarsh_WT_dataSignalMapping.csv` | https://zenodo.org/records/16807551/files/Kelmarsh_WT_dataSignalMapping.csv?download=1 | ca8fe399ab15ae7111d3214c632efd36 |
| `Kelmarsh_SCADA_2022_4457.zip` | https://zenodo.org/records/16807551/files/Kelmarsh_SCADA_2022_4457.zip?download=1 | b695d2b21cd5a236b2e690e0a43df5ab |

The SCADA zip is about 490 MB. The download script must skip files that already exist with the correct MD5.

## 3. Scope

In scope:

- One year of SCADA data (2022), all 6 turbines.
- A small set of signals: wind speed, active power, wind direction, nacelle direction, ambient temperature, blade pitch angle, rotor speed.
- One LightGBM power model per turbine.
- Rule-based underperformance alerts.
- An in-memory RDF graph with rdflib, serialized to Turtle.
- A Streamlit dashboard with a replay control.

Out of scope:

- Other years, PMU data and grid meter data.
- Component health models and wake models.
- Triple stores, SHACL validation, RDS-PP designation codes.
- MQTT, Kafka or any real streaming infrastructure.
- Formal backtesting against event logs.

## 4. Tech stack

- Python 3.11 or later
- uv for Python version, virtual environment and package management
- pandas, pyarrow, duckdb
- lightgbm, scikit-learn
- rdflib
- streamlit, plotly
- pyyaml, requests, tqdm

Manage the project with uv:

- Initialise with `uv init` and pin Python with `uv python pin 3.11`.
- Add dependencies with `uv add <package>`, so they are declared in `pyproject.toml`.
- Commit `uv.lock` for reproducible installs.
- Run every script with `uv run`.
- Do not use pip, `requirements.txt` or a manually created venv.

## 5. Repository layout

```
kelmarsh-twin/
  README.md
  pyproject.toml
  uv.lock
  .python-version
  config.yaml
  data/
    raw/            # downloaded files, git-ignored
    processed/      # parquet files, git-ignored
  ontology/
    kelmarsh.ttl    # generated graph
  models/           # trained models and metrics, git-ignored
  src/
    download.py
    inspect_data.py
    load_scada.py
    clean.py
    build_ontology.py
    train.py
    alerts.py
    graph_utils.py
  app/
    app.py
  Makefile
```

## 6. Configuration

All paths, column names and thresholds live in `config.yaml`. No hard-coded values in scripts. Initial content:

```yaml
year: 2022
paths:
  raw: data/raw
  processed: data/processed
  ontology: ontology/kelmarsh.ttl
  models: models
signals:
  # Fill in exact column names after running inspect_data.py
  wind_speed: "Wind speed (m/s)"
  power: "Power (kW)"
  wind_direction: "Wind direction (°)"
  nacelle_direction: "Nacelle position (°)"
  ambient_temp: "Ambient temperature (converter) (°C)"
  pitch: "Blade angle (pitch position) A (°)"
  rotor_speed: "Rotor speed (RPM)"
cleaning:
  min_wind_speed: 3.0
  max_wind_speed: 25.0
  max_pitch_deg: 5.0
  min_power_kw: 0.0
train_test_split:
  train_end: "2022-09-30 23:50"
alerts:
  window_samples: 144          # 24 hours of 10-minute data
  threshold_fraction: -0.05    # mean residual below -5% of rated power
  min_duration_samples: 36     # 6 hours
```

The column names above are guesses. Section 7.2 requires confirming them from the real files before use.

## 7. Components

### 7.1 `download.py`

- Download the three files in section 2 into `data/raw/`.
- Verify MD5. Skip a file if it exists and the MD5 matches.
- Unzip the SCADA archive into `data/raw/scada_2022/`.
- Show a progress bar.

Acceptance: running it twice downloads nothing the second time.

### 7.2 `inspect_data.py`

Run this before writing the loader. It must:

- List the files inside the SCADA folder and group them by type. The archive contains turbine data files and may contain status or event files. Identify which is which from the file names.
- For one turbine data file, print the first 15 raw lines so the header structure is visible. The files may have metadata lines above the column header.
- Print the full list of column names.
- Print the columns of the static and mapping CSVs.

Acceptance: the developer can fill in `config.yaml` signal names from this output. Update `config.yaml` with the confirmed names before moving on.

### 7.3 `load_scada.py`

- Read every turbine data file for 2022.
- Handle any metadata lines above the header.
- Parse the timestamp column to UTC datetime.
- Derive `turbine_id` (T01 to T06) from the file name or the static file. Use the same IDs everywhere.
- Keep only the timestamp, `turbine_id` and the signals in `config.yaml`. Rename them to the config keys (`wind_speed`, `power`, and so on).
- Write one Parquet file per turbine to `data/processed/scada_<turbine_id>.parquet`.

Acceptance: 6 Parquet files exist. Each has about 52,560 rows (one year of 10-minute data), possibly fewer due to gaps. Print row counts and missing value percentages per column.

### 7.4 `clean.py`

Add a boolean column `is_normal` to each Parquet file. A row is normal when all of these hold:

- No missing values in the model inputs or the target.
- `wind_speed` between `min_wind_speed` and `max_wind_speed`.
- `power` above `min_power_kw`.
- `pitch` below `max_pitch_deg` when wind speed is below rated wind speed (about 12 m/s for MM92). This removes most curtailment and derating.

Also add `air_density` computed from ambient temperature with standard pressure (101325 Pa) and the ideal gas law.

Acceptance: print the share of normal rows per turbine. Expect roughly 50 to 80 percent. Save a scatter plot of wind speed vs power per turbine to `models/power_curve_<turbine_id>.png`, with normal and excluded points in different colours.

### 7.5 `build_ontology.py`

Build the graph with rdflib and write it to `ontology/kelmarsh.ttl`.

Namespaces:

| Prefix | IRI |
|---|---|
| `kt` | `https://example.org/kelmarsh-twin#` |
| `sosa` | `http://www.w3.org/ns/sosa/` |
| `prov` | `http://www.w3.org/ns/prov#` |
| `qudt` | `http://qudt.org/schema/qudt/` |
| `unit` | `http://qudt.org/vocab/unit/` |
| `geo` | `http://www.w3.org/2003/01/geo/wgs84_pos#` |

Classes:

| Class | Description |
|---|---|
| `kt:WindFarm` | The Kelmarsh site |
| `kt:Turbine` | One wind turbine |
| `kt:Component` | Superclass for turbine parts |
| `kt:Rotor`, `kt:Generator`, `kt:Nacelle` | Subclasses of `kt:Component` |
| `sosa:Sensor` | One SCADA signal |
| `kt:PowerModel` | A trained power model, also a `prov:Entity` |
| `kt:Alert` | An underperformance alert |

Properties:

| Property | Domain | Range |
|---|---|---|
| `kt:hasTurbine` | WindFarm | Turbine |
| `kt:hasComponent` | Turbine | Component |
| `kt:hasSensor` | Turbine | sosa:Sensor |
| `kt:attachedTo` | sosa:Sensor | Component |
| `sosa:observes` | sosa:Sensor | observable property IRI, e.g. `kt:WindSpeed` |
| `qudt:unit` | sosa:Sensor | QUDT unit |
| `kt:signalKey` | sosa:Sensor | string, the config key, e.g. `power` |
| `kt:scadaColumn` | sosa:Sensor | string, the original column name |
| `kt:storedIn` | sosa:Sensor | string, Parquet path |
| `kt:ratedPowerKW`, `kt:rotorDiameterM`, `kt:hubHeightM` | Turbine | decimal |
| `geo:lat`, `geo:long` | Turbine | decimal |
| `kt:forTurbine` | PowerModel | Turbine |
| `kt:usesInput` | PowerModel | sosa:Sensor |
| `kt:target` | PowerModel | sosa:Sensor |
| `kt:maeKW`, `kt:nmae` | PowerModel | decimal |
| `kt:raisedBy` | Alert | PowerModel |
| `kt:concerns` | Alert | Turbine |
| `kt:startTime`, `kt:endTime` | Alert | xsd:dateTime |
| `kt:meanResidualFraction` | Alert | decimal |
| `kt:lostEnergyMWh` | Alert | decimal |

Rules:

- Populate turbines from `Kelmarsh_WT_static.csv` (coordinates, rated power, rotor diameter, hub height). Use the real values in the file.
- Create one sensor per turbine per signal in `config.yaml`. Attach each to a sensible component: wind speed, wind direction and ambient temperature to `Nacelle`; pitch and rotor speed to `Rotor`; power to `Generator`.
- Use the mapping CSV to record the original SCADA signal name where a match exists.
- Write the ontology schema (classes and properties with `rdfs:label` and `rdfs:comment`) into the same file, at the top.

Acceptance: the file parses with rdflib. A test query returns 6 turbines, each with 7 sensors and coordinates.

### 7.6 `graph_utils.py`

Helper functions used by other scripts and the app:

- `load_graph(path) -> rdflib.Graph`
- `get_turbines(g) -> pandas.DataFrame` with id, lat, long, rated power.
- `get_sensors(g, turbine_id) -> pandas.DataFrame` with signal key, column, unit, Parquet path.
- `get_model_inputs(g, turbine_id) -> list[str]` returning signal keys.
- `get_alerts(g, turbine_id=None) -> pandas.DataFrame`.
- `add_model(g, ...)` and `add_alert(g, ...)`.

All lookups must use SPARQL queries, so the app reads structure from the graph and not from config.

### 7.7 `train.py`

For each turbine:

- Read the Parquet path and input signals from the graph via `graph_utils`.
- Features: `wind_speed`, `air_density`, `wind_direction`, and `sin` and `cos` of wind direction. Target: `power`.
- Train on normal rows up to `train_end`. Test on normal rows after it.
- Model: `lightgbm.LGBMRegressor` with default parameters plus `n_estimators=300`.
- Compute MAE in kW and normalised MAE (MAE divided by rated power) on the test set.
- Save the model to `models/power_<turbine_id>.txt`.
- Predict `expected_power` for all rows (normal and not) and save it into the turbine Parquet file.
- Add a `kt:PowerModel` node to the graph with inputs, target, metrics and `prov:generatedAtTime`.
- Write `models/metrics.json` with metrics for all turbines.

Acceptance: normalised MAE below 0.05 for every turbine on the test set. If a turbine fails this, print a warning and continue.

### 7.8 `alerts.py`

For each turbine, on normal rows only:

- `residual_fraction = (power - expected_power) / rated_power`
- Rolling mean over `window_samples`.
- Mark samples where the rolling mean is below `threshold_fraction`.
- Merge consecutive marked samples into periods. Drop periods shorter than `min_duration_samples`.
- For each period compute mean residual fraction and lost energy in MWh (sum of `expected_power - power` in kW times 1/6 h, divided by 1000).
- Add each period to the graph as a `kt:Alert`, linked to its turbine and model.
- Serialize the updated graph to `ontology/kelmarsh.ttl`.

Acceptance: print alert count and total lost energy per turbine. Zero alerts is a valid result, but print a note suggesting a looser threshold if all turbines have zero.

### 7.9 `app/app.py` (Streamlit)

Read turbines, sensors, models and alerts from the graph. Read time series from Parquet through DuckDB.

Layout:

- Sidebar: turbine selector, replay date slider over 2022, play and pause buttons, replay speed selector (1, 6 or 24 samples per tick).
- Top row: a map of the 6 turbines from the graph coordinates. Colour each turbine by status at the current replay time: green when normal, amber when not normal, red when inside an alert period.
- Middle: KPI cards for the selected turbine at the current replay time. Show actual power, expected power, residual fraction, and wind speed.
- Chart: actual and expected power over the last 7 days up to the replay time, with alert periods shaded.
- Chart: power curve scatter for the selected turbine, with the current point highlighted.
- Table: alerts from the graph for the selected turbine, with start, end, mean residual and lost energy.
- Expander: "Ontology view", showing the SPARQL query used and the sensors table for the selected turbine.
- Footer: dataset attribution with DOI and license.

Replay must use `st.session_state` and `st.rerun()` with a short sleep. It must not block the UI.

Acceptance: `uv run streamlit run app/app.py` starts without errors. Playing the replay moves the charts forward and changes turbine colours when alerts start and end.

### 7.10 `Makefile`

Targets:

```
make setup      # uv sync
make download
make inspect
make data       # load_scada + clean
make ontology
make train
make alerts
make app
make all        # download through alerts
```

Each target calls its script through uv, for example `uv run python -m src.download`.

### 7.11 `README.md`

- One-paragraph description of the PoC.
- Diagram of the pipeline (Mermaid is fine).
- How to run: install uv, run `uv sync`, then use the Makefile targets.
- Results table copied from `models/metrics.json` and alert summary.
- Known limitations: one year only, simple cleaning rules, no validation against event logs.
- Attribution to Cubico Sustainable Investments Ltd, DOI and CC-BY-4.0 license.

## 8. Instructions for Claude Code

- Work through the components in order. Run each script and check its acceptance criteria before starting the next.
- Run `inspect_data.py` and update `config.yaml` with the real column names before writing `load_scada.py`. Do not guess column names.
- If the real data differs from this spec (file layout, column names, units), adapt the code to the data and record the change in a "Deviations from spec" section at the end of the README.
- Keep each script runnable on its own with `uv run python -m src.<name>`.
- Add packages only with `uv add`. Never call pip directly.
- Use type hints and short docstrings. Use `logging` for output.
- Do not commit anything under `data/` or `models/`.
- Ask before adding any dependency not listed in section 4.

## 9. Definition of done

- `uv sync` followed by `make all` runs from a clean clone and finishes without errors.
- `ontology/kelmarsh.ttl` contains the schema, 6 turbines, 42 sensors, 6 power models and all alerts.
- `models/metrics.json` exists with metrics for all turbines.
- The Streamlit app runs and the replay works.
- The README documents results, limitations, deviations and attribution.

## 10. Possible next steps after the PoC

- Add health models for gearbox and generator bearing temperatures.
- Validate alerts against the event and status logs.
- Extend to 2016 to 2024 and add grid meter reconciliation.
- Add a PyWake farm model for wake losses.
- Move the graph to a triple store and add SHACL validation.
## 11. Change log

### Milestone 1: scaffold

- Initialised the uv project (`kelmarsh-twin`, Python 3.11 pinned) and added the
  §4 dependencies plus `matplotlib` (power curve PNGs) and dev dependencies
  `pytest` and `ruff`.
- Added `config.yaml` with the §6 content plus `downloads` (URLs, MD5s),
  `sampling.interval_minutes`, `cleaning.rated_wind_speed` and
  `cleaning.standard_pressure_pa`, so scripts hold no hard-coded values.
- Added `src/config.py` (`load_config`), the `Makefile` (§7.10 targets plus
  `test` and `lint`), and `tests/test_config.py`.

### Milestone 2: `download.py`

- Added `src/download.py`: streams each configured file to a `.part` file
  with a tqdm progress bar, verifies the MD5 (raises on mismatch), skips files
  already present with the correct MD5, and unzips the SCADA archive into
  `data/raw/scada_2022/` unless all members are already extracted.
- Pure helpers (`md5_of`, `needs_download`, `ensure_file` with an injectable
  fetcher, `extract`) are covered by `tests/test_download.py` without network.

### Milestone 3: `inspect_data.py`

- Added `src/scada_format.py` (file classification and grouping, BOM/CRLF
  safe `read_head`, `header_line_index`, `parse_columns`), shared with the
  loader, and `src/inspect_data.py`, which prints the file groups, the first
  15 raw lines, all 303 columns and the static/mapping CSV columns.
- Findings: header is the commented line 10 (`# Date and time,…`) in all 6
  turbine files; all 7 §6 signal names exist exactly, so `config.yaml` keeps
  them, now marked as confirmed. Deviations recorded in the README.

### Milestone 4: `load_scada.py`

- Added `src/load_scada.py`: reads the timestamp and the 7 configured signal
  columns from each `Turbine_Data_*.csv` (skipping the metadata lines),
  renames them to the config keys, parses timestamps as UTC, keeps only
  `year`, drops duplicate timestamps and writes
  `data/processed/scada_<turbine_id>.parquet`.
- Turbine ids `T01`–`T06` come from `Kelmarsh_<N>` in the file name
  (`scada_format.turbine_id_from_filename`, `format_turbine_id`).
- `config.yaml` gained `scada.timestamp_column`.
- Result: 6 files, 52,560 rows each; missing values 0.1–1.1 % per signal.
