# Kelmarsh Wind Farm Digital Twin PoC: Specification

## 1. Goal

Build a proof of concept of a data-driven digital twin for Kelmarsh wind farm (UK, 6 x Senvion MM92, 12.3 MW). The PoC must show the full chain in one working demo:

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
| `Kelmarsh_SCADA_<year>_<id>.zip` (2016–2024) | https://zenodo.org/records/16807551/files/Kelmarsh_SCADA_<year>_<id>.zip?download=1 | see §10.1 and `config.yaml` |

The 9 SCADA zips total about 3.7 GB (about 43 GB unzipped; the 2022 zip alone is about 490 MB). The download script must skip files that already exist with the correct MD5.

## 3. Scope

In scope:

- SCADA data for 2016–2024 (originally one year, 2022; extended per §10.1), all 6 turbines.
- A small set of signals: wind speed, active power, wind direction, nacelle direction, ambient temperature, blade pitch angle, rotor speed.
- One LightGBM power model per turbine.
- Rule-based underperformance alerts.
- An in-memory RDF graph with rdflib, serialized to Turtle.
- A Streamlit dashboard with a replay control.

Out of scope:

- PMU data and grid meter data.
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

- Download the files in section 2 (2 CSVs and 9 SCADA zips) into `data/raw/`.
- Verify MD5. Skip a file if it exists and the MD5 matches.
- Unzip each SCADA archive into its own `data/raw/scada_<year>/` folder (`extract_to` in `config.yaml`).
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

- Read every turbine data file of every configured year (`years`), combine the files of each turbine, keep only rows of those years and drop duplicate timestamps (keep the row with the most non-missing signals).
- Handle any metadata lines above the header.
- Parse the timestamp column to UTC datetime.
- Derive `turbine_id` (T01 to T06) from the file name or the static file. Use the same IDs everywhere.
- Keep only the timestamp, `turbine_id` and the signals in `config.yaml`. Rename them to the config keys (`wind_speed`, `power`, and so on).
- Write one Parquet file per turbine to `data/processed/scada_<turbine_id>.parquet`.

Acceptance: 6 Parquet files exist. Each has about 52,560 rows per year (10-minute data), possibly fewer due to gaps. Print row counts, rows per year and missing value percentages per column.

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

- Sidebar: turbine selector, replay date picker over the loaded data (2016–2024) plus a time-of-day slider in 10-minute steps, play and pause buttons, replay speed selector (10 min, 1 h, 4 h, 1 day or 1 week per tick). The replay opens at the first sample of the test period (after `train_test_split.train_end`). A "Replay year only" checkbox (on by default) limits the power curve and alerts table to the replay year; unchecked, a year range is chosen.
- Top row: a map of the 6 turbines from the graph coordinates. Colour each turbine by status at the current replay time: green when normal, amber when not normal, red when inside an alert period.
- Middle: KPI cards for the selected turbine at the current replay time. Show actual power, expected power, residual fraction, and wind speed.
- Chart: actual and expected power over the last 7 days up to the replay time, with alert periods shaded.
- Chart: power curve scatter for the selected turbine, with the current point highlighted.
- Table: alerts from the graph for the selected turbine, with start, end, mean residual and lost energy.
- Expander: "Ontology view", showing the SPARQL query used and the sensors table for the selected turbine.
- "Overview" tab: a heatmap of the monthly mean residual fraction (normal rows) of all turbines over all years, and a yearly summary table of the selected turbine (energy, normal share, mean residual fraction, alert count and lost energy, alerts counted in their start year).
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
- Known limitations: simple cleaning rules, no validation against event logs.
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

### 10.1 Future work: multi-year SCADA data (2016–2024)

Status: done (see the change log, "Feature: multi-year SCADA data"). The
plan below is kept as written; open decisions were settled as: all years
2016–2024, train on 2016–2021 and test on 2022–2024, everything downloaded
before coding.

**Available data** (Zenodo record 16807551, checked 2026-11-12 via the
Zenodo API; about 3.7 GB zipped, roughly 13 GB on disk once unzipped):

| File | MD5 |
|---|---|
| `Kelmarsh_SCADA_2016_3082.zip` | ca8efbb6dbcfae3516583937eb5b5402 |
| `Kelmarsh_SCADA_2017_3083.zip` | c78263ee52ee0e48e2cb4bbaa1ba211a |
| `Kelmarsh_SCADA_2018_3084.zip` | 972e5280172216a5fe76dcab19c741b0 |
| `Kelmarsh_SCADA_2019_3085.zip` | 14348a1572b722e1be10e53cd145c39a |
| `Kelmarsh_SCADA_2020_3086.zip` | e189e02da98f32e74acc72e8559ef0db |
| `Kelmarsh_SCADA_2021_4456.zip` | 4e0ef3d65f067fd3d8f3d30e79ab01ae |
| `Kelmarsh_SCADA_2022_4457.zip` | b695d2b21cd5a236b2e690e0a43df5ab |
| `Kelmarsh_SCADA_2023_5961.zip` | 685d9589347d1866f6f2cfe45b9af4f4 |
| `Kelmarsh_SCADA_2024_5962.zip` | e9e3318f5b393d8596ff1801f8da0414 |

URLs follow `https://zenodo.org/records/16807551/files/<file>?download=1`.
2016 is likely a partial year (commercial operation from 15 April 2016).

**Single-year assumptions in the current code:**

| Where | Problem with several years |
|---|---|
| `download.py` (`main`) | Downloads every listed file but unzips only the first `.zip`, into the single `downloads.scada_dir` folder. |
| `load_scada.py` (`tidy`, `main`) | Keeps only rows of `config.year`. Writes one Parquet per raw file, so several files per turbine in one folder overwrite each other: silent data loss. |
| `build_ontology.py` (`turbine_files_in`, `add_sources`) | Provenance assumes one raw file per turbine and one SCADA zip. |
| `config.yaml` | `year`, `downloads.scada_dir` and `train_test_split.train_end` are single values. |

Already year-agnostic: `clean.py`, `train.py` (apart from `train_end`),
`alerts.py`, all `graph_utils` SPARQL lookups, and the dashboard replay
range (taken from the data). If a year's export has different column names,
`load_scada.py` stops with an error naming the missing columns.

**Planned changes:**

1. `config.yaml`: replace `year` with `years: [...]`; list each SCADA zip in
   `downloads.files` with its own folder (`scada_<year>/`).
2. `download.py`: unzip every listed archive into its own folder.
3. Run `inspect_data.py` per new year and confirm the signal column names
   (2023 and 2024 archives are noticeably larger; the layout may differ).
   Record any differences under "Deviations from spec" in the README.
4. `load_scada.py`: gather all raw files per turbine, concatenate, keep the
   configured years, drop duplicate timestamps at year boundaries, write one
   Parquet per turbine.
5. `build_ontology.py`: link each sensor to all its raw files
   (`prov:wasDerivedFrom`), each `kt:partOf` its own zip.
6. `train_test_split.train_end`: e.g. train on 2016–2021, test on 2022–2024;
   more training seasons should reduce the October drift seen in the 2022
   alerts.
7. Tests: multi-year loading (no overwrite, boundary duplicates, year
   filter), multi-archive extraction, multi-file provenance.
8. Dashboard: about 2.8 million rows for 6 turbines × 9 years are held in
   memory; sample the power-curve scatter if it becomes slow.

**Open decisions:** which years to include, the train/test split, and
whether to download everything or develop against 2022 first.
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

### Milestone 5: `clean.py`

- Added `src/clean.py`: `normal_mask` implements the four §7.4 rules,
  `air_density` uses the ideal gas law with dry-air R = 287.05 J/(kg K) and
  `cleaning.standard_pressure_pa`; both columns are written back into each
  Parquet file, and `models/power_curve_<turbine_id>.png` is saved.
- `config.yaml` gained `model.inputs` / `model.target`, used for the
  completeness rule now and for the ontology's model inputs later.
- Result: 74.1–80.8 % normal rows per turbine. Known limitation: a derating
  plateau near 1,650 kW above rated wind stays normal (README).

### Milestone 6: `build_ontology.py` and `graph_utils.py`

- Added `src/graph_utils.py`: namespaces, deterministic IRIs (`kt:T01`,
  `kt:T01_power`, `kt:PowerModel_T01`, `kt:Alert_T01_001`), `load_graph`,
  `save_graph` (schema block first), SPARQL-backed `get_turbines`,
  `get_sensors`, `get_model_inputs`, `get_alerts`, and `add_model` (replaces
  an existing node) and `add_alert`.
- Added `src/build_ontology.py`: schema with labels/comments, farm, 6
  turbines with real static values, 3 components each, 42 sensors with QUDT
  units and mapping-CSV titles, and one `kt:PowerModel` per turbine declaring
  inputs/target from `config.yaml`.
- Result: 805 triples; acceptance query returns 6 turbines × 7 sensors with
  coordinates. Extensions and the `kWh` mapping quirk are in the README.

### Milestone 7: `train.py`

- Added `src/train.py`: per turbine from the graph, reads inputs, target and
  Parquet path via `graph_utils`, derives the §7.7 features (wind speed, air
  density, wind direction and its sin/cos), trains `LGBMRegressor`
  (`n_estimators=300`) on normal rows up to `train_end`, scores MAE/nMAE on
  later normal rows, saves `models/power_<id>.txt`, writes `expected_power`
  into the Parquet file, replaces the `kt:PowerModel` node with metrics and
  `prov:generatedAtTime`, and writes `models/metrics.json`.
- Added `graph_utils.get_model_target`.
- Result: nMAE 0.026–0.039 (MAE 54–80 kW) on Q4 2022; all below 0.05.
  Re-running keeps exactly 6 model nodes.

### Milestone 8: `alerts.py`

- Added `src/alerts.py`: on normal rows, residual fraction, trailing rolling
  mean over `window_samples` (full window required), marks below
  `threshold_fraction`, merges consecutive marks into periods, drops those
  shorter than `min_duration_samples`, computes mean residual fraction and
  lost energy (kW × interval / 60 / 1000), and writes `kt:Alert` nodes linked
  to turbine and model.
- Added `graph_utils.remove_alerts` so re-runs replace alerts.
- Result: 9 alerts, 28.1 MWh lost (T01 3 / 3.0, T02 3 / 19.2, T03 0,
  T04 2 / 5.2, T05 0, T06 1 / 0.6). Most fall in October 2022, just after
  `train_end`.

### Milestone 9: `app/app.py`

- Added `src/dashboard.py` (DuckDB loading in UTC, `row_at`, `in_alert`,
  `turbine_status`, `window`, `alerts_overlapping`, `kpis`, `advance`) and
  `app/app.py`: sidebar turbine selector, replay slider, play/pause
  (callbacks + `st.session_state`, `time.sleep(0.5)` + `st.rerun()`), speed
  1/6/24 samples per tick; status map, KPI cards, 7-day actual vs expected
  chart with shaded alerts, power curve with current point, alerts table,
  "Ontology view" expander with the SPARQL query and sensors, attribution.
- Added `graph_utils.get_models`; moved `parquet_path_of` from `train.py` to
  `graph_utils` (tests unchanged apart from the import).
- Checked: server starts (health `ok`, HTTP 200); playing advances the replay
  (11 ticks of 6 samples in 6 s); T02 turns red at 2022-10-04 19:50 and back
  at 2022-10-08 14:20, matching its alert.

### Dev dependency: `watchdog`

- Added `watchdog` to the dev dependency group (user approved) so Streamlit
  watches files efficiently during development; not needed by the pipeline.

### Milestone 10: README and definition of done

- README completed: pipeline Mermaid diagram, results (data, model metrics
  from `models/metrics.json`, alert summary, graph contents), extra known
  limitations (seasonal drift after `train_end`, in-memory replay).
- Definition of done checked in a fresh clone (raw files copied in, so the
  download step verified MD5s and unzipped without re-downloading):
  `uv sync` + `make all` finished without errors in 72 s; the graph holds the
  schema (9 classes, 28 properties), 6 turbines, 42 sensors, 6 trained power
  models and 9 alerts; `models/metrics.json` covers all 6 turbines; all 91
  tests pass there (including the app smoke tests); the app starts cleanly.

### Fix: status map not showing the turbines

- plotly 7.1 `px.scatter_map` no longer centres the map on the data
  (`layout.map.center` stayed empty), so MapLibre opened at lat 0 / lon 0 at
  zoom 13.5 and the turbines were off-screen. Added
  `dashboard.map_center` (mean turbine position) and pass it as `center`.
- Tests: unit test for `map_center`, and an `AppTest` check that the rendered
  map spec is centred on Kelmarsh (both failed before the fix).

### Feature: ontology & lineage tab

- Graph gains provenance: `kt:Dataset`, `kt:SourceFile`,
  `prov:wasDerivedFrom` (turbine → static CSV; sensor → raw SCADA file and
  mapping CSV), `kt:partOf` (raw file → zip → dataset), file URL/MD5, DOI,
  publisher, license, model file, and turbine manufacturer, model and
  commissioning date. `config.yaml` gained `dataset`.
- `graph_utils`: `get_lineage` and `get_schema` (SPARQL), `source_iri`,
  `DATASET_IRI`, `add_model(model_file=...)`.
- New `src/ontology_view.py` renders lineage and schema as Graphviz DOT;
  `dashboard.active_alerts` marks alerts inside the replay time.
- `app/app.py` now has tabs "Replay" and "Ontology & lineage" (sensor filter,
  lineage graph, schema graph, the SPARQL queries). No new dependency
  (`st.graphviz_chart`).
- Graph now 1,134 triples: 11 classes, 40 properties, 9 source files.

### Change: satellite base map

- `config.yaml` gained `dashboard.map_style` (default `satellite`, plotly's
  Esri World Imagery style, no token needed); `status_map` takes the style
  as a parameter and draws white turbine labels for contrast.
- Tests: config default and an `AppTest` check that the rendered map uses
  the configured style.

### Feature: multi-year SCADA data (2016–2024)

Implements the plan in §10.1 on branch `feature/multi-year-scada`.

- `config.yaml`: `year` → `years: [2016 … 2024]`; the 9 SCADA zips are
  listed in `downloads.files`, each with an `extract_to: scada_<year>` folder
  (replaces `downloads.scada_dir`); `train_end` → `2021-12-31 23:50`;
  `dashboard.power_curve_max_points: 50000`.
- `src/config.py`: `scada_archives` and `scada_dirs` (download entries with
  `extract_to` and their folders).
- `download.py`: `extract_archives` unzips every SCADA archive into its own
  folder.
- `scada_format.py`: `turbine_data_files` and `group_by_turbine`, shared by
  `load_scada.py` and `build_ontology.py` (replaces
  `build_ontology.turbine_files_in`).
- `load_scada.py`: one Parquet per turbine from all its yearly files; keeps
  the configured years; on duplicate timestamps keeps the row with the most
  non-missing signals (the 2023/2024 exports repeat rows, some as all-NaN
  copies that can come first); prints rows per year.
- `build_ontology.py`: each sensor `prov:wasDerivedFrom` all its yearly raw
  files; each raw file `kt:partOf` its own year's zip. Graph: 1,670 triples,
  65 source files, 27 alerts.
- `inspect_data.py`: inspects every year folder and lists configured columns
  missing per turbine data file (none: all 7 signals present in all 54 files).
- Dashboard: power curve draws a reproducible sample of at most 50,000
  normal rows (`dashboard.sample_rows`); `render_replay` takes the
  `dashboard` config section.
- Tests: multi-year loading (year filter, no overwrite, boundary
  duplicates, complete row preferred over earlier NaN copy, rows per year),
  multi-archive extraction, file discovery and grouping, multi-file
  provenance (fixture: T01 has 2021 and 2022 files), config helpers,
  `missing_columns`, `sample_rows`. The shipped-config test now expects
  11 downloads instead of 3.
- Result: 473,184 rows per turbine; nMAE 0.023–0.028 on 2022–2024 (was
  0.026–0.039 on Q4 2022 with the 2022-only models); 27 alerts, 111.3 MWh,
  led by T04 in February–April 2023 (59.1 MWh). `make all` takes about
  160 s once downloaded (`load_scada` about 140 s).

### Change: dashboard for multi-year data

Navigating and summarising 9 years of data in the dashboard (§7.9 updated).

- Replay time: a date picker plus a time-of-day slider replace the single
  10-minute slider (about 473k steps over 2016–2024); both mirror
  `replay_time`, which playing advances. The replay opens at the start of
  the test period (2022-01-01 00:00) instead of the first timestamp.
- Speeds: 10 min, 1 h, 4 h, 1 day and 1 week per tick (were 1, 6 and 24
  samples); a year now plays in about 5 minutes at 1 day per tick.
- Power curve and alerts table cover the replay year by default, or a
  chosen year range.
- New "Overview" tab: monthly mean residual heatmap of all turbines and a
  yearly summary per turbine, computed once and cached.
- `src/dashboard.py`: `clamp`, `replay_start`, `year_span`, `rows_between`,
  `with_residual`, `monthly_residuals`, `yearly_summary`, with tests; new
  app tests for the start time, date picker, speeds, year filter and
  overview tab. The tab-label assertion now includes "Overview".
