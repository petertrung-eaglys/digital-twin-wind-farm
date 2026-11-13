# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project state

The proof of concept is **implemented end to end** (spec §7.1–7.11 done, definition of done in §9 verified from a clean clone). `docs/spec.md` is the authoritative specification; its §11 change log records every milestone and later change, and `README.md` holds results, known limitations and a "Deviations from spec" section. Read the spec (including §10.1) and the README deviations before changing behaviour.

## Project

Proof-of-concept data-driven digital twin for the Kelmarsh wind farm (6x Senvion MM92 turbines), built around a Zenodo SCADA dataset (record 16807551, 2016–2024 data; originally 2022 only). The PoC favours a complete end-to-end slice over accuracy or completeness.

## Package management: uv only

This project is managed exclusively through `uv` — no `pip`, no `requirements.txt`, no manually created venv. Python is pinned to 3.11 (`.python-version`).

- Add dependencies with `uv add <package>` (dev tools with `uv add --dev`) — this is the only way new packages enter `pyproject.toml`. Ask before adding any dependency not listed in spec §4. Approved additions so far: `matplotlib` (runtime), `pytest`, `ruff`, `watchdog` (dev).
- Commit `uv.lock` for reproducible installs.
- Run every script through `uv run`, e.g. `uv run python -m src.<name>`, `uv run streamlit run app/app.py`.

## Commands

Via the `Makefile` (each target shells out through `uv run`):

```
make setup      # uv sync
make download   # fetch raw files into data/raw/ (MD5-verified, skips existing), unzip SCADA
make inspect    # print raw file structure and column names
make data       # load_scada.py + clean.py
make ontology   # build_ontology.py
make train      # train.py
make alerts     # alerts.py
make app        # uv run streamlit run app/app.py
make all        # download through alerts, end to end (~160 s once downloaded)
make test       # uv run pytest
make lint       # uv run ruff check .
```

Each script is also runnable standalone: `uv run python -m src.<name>`. Run a single test with `uv run pytest tests/test_alerts.py::test_short_periods_are_dropped`. Format with `uv run ruff format .`.

## Pipeline order

The pipeline has a strict dependency order:

1. `download.py` — fetch the files listed in `config.yaml` `downloads` into `data/raw/` (~3.7 GB), verify MD5, skip valid files, unzip each SCADA archive into its `extract_to` folder (`data/raw/scada_<year>/`, ~43 GB in total).
2. `inspect_data.py` — prints raw file structure per year folder and the configured columns missing from each turbine file. Run it before changing the loader or adding data; do not guess column names. The 7 signal names in `config.yaml` are confirmed for all years 2016–2024.
3. `load_scada.py` → `clean.py` — all yearly files of a turbine combined into one Parquet per turbine in `data/processed/scada_<T0N>.parquet` (rows of `config.years` only, duplicate timestamps resolved), then `is_normal` and `air_density` added in place.
4. `build_ontology.py` — schema, provenance (dataset, source files), farm, turbines, components, sensors, and one `kt:PowerModel` per turbine declaring inputs/target from `config.yaml`. Overwrites `ontology/kelmarsh.ttl`, so `train` and `alerts` must run again after it.
5. `train.py` — one LightGBM model per turbine; writes `expected_power` to Parquet, replaces the `kt:PowerModel` node (metrics, `prov:generatedAtTime`, model file), writes `models/metrics.json`.
6. `alerts.py` — rolling-residual underperformance periods, written to the graph as `kt:Alert` (replacing the turbine's previous alerts).
7. `app/app.py` — Streamlit dashboard with "Replay", "Overview" and "Ontology & lineage" tabs; reads structure from the graph and time series from Parquet via DuckDB.

## Module map

- `src/config.py` — `load_config()`, plus `scada_archives()` / `scada_dirs()` (download entries with `extract_to` and their folders); `config.yaml` holds `years`, paths, downloads, dataset metadata, column names, model inputs/target, thresholds and `dashboard` settings. No hard-coded values in scripts.
- `src/scada_format.py` — Greenbyte export layout: file discovery across year folders (`turbine_data_files`, `group_by_turbine`), file classification, header detection, turbine ids (`T01`–`T06` from `Kelmarsh_<N>` in file names).
- `src/graph_utils.py` — the only module that talks to the graph (see below).
- `src/dashboard.py` — pure helpers for the app (DuckDB loading, status, KPIs, windows, replay stepping, active alerts, map centre, power-curve sampling).
- `src/ontology_view.py` — pure Graphviz DOT rendering of the lineage subgraph and the schema.
- `app/app.py` — rendering only; logic lives in `src/dashboard.py` and `src/ontology_view.py` so it can be unit-tested.

## Architecture: the RDF graph is the source of structural truth

The central design point (easy to miss without reading multiple files): **`ontology/kelmarsh.ttl` — not `config.yaml` — is what the app and downstream scripts query for structure.** `config.yaml` only holds raw paths, column-name mappings, metadata and numeric thresholds used while *building* the graph or running steps.

- `graph_utils.py` is the only place that talks to the graph directly. Lookups are SPARQL queries (module-level `*_QUERY` constants, shown in the app): `get_turbines`, `get_sensors`, `get_model_inputs`, `get_model_target`, `get_models`, `get_alerts`, `get_lineage`, `get_schema`. Writers: `add_model` (replaces the node), `add_alert`, `remove_alerts`. Also `load_graph`, `save_graph` (writes the schema block first), `parquet_path_of`.
- Every other script (`train.py`, `alerts.py`, `app/app.py`) goes through `graph_utils.py` to discover turbines, sensor→Parquet-path mappings and model inputs — never `config.yaml` for this.
- IRIs are deterministic (`kt:T01`, `kt:T01_power`, `kt:PowerModel_T01`, `kt:Alert_T01_001`, `kt:Source_<file>`), so re-running `train` or `alerts` replaces nodes instead of duplicating them.
- Raw time-series values live in per-turbine Parquet files; the graph stores only metadata and relationships, with `kt:storedIn` pointing at the Parquet path and `kt:scadaColumn`/`kt:signalKey` bridging back to the SCADA column names.
- Provenance: turbines `prov:wasDerivedFrom` the static CSV; sensors `prov:wasDerivedFrom` all their yearly raw SCADA files and, where matched, the mapping CSV; each raw file is `kt:partOf` its year's zip (looked up from the folder via `extract_to`), which is `kt:partOf` the `kt:Dataset`. The lineage tab renders this.
- `air_density` and the sin/cos of wind direction are derived features, not sensors; the model's sensor inputs are `wind_speed`, `wind_direction`, `ambient_temp`.

## Testing

- Tests use small synthetic data and never the network; `tests/conftest.py` builds a 2-turbine graph via `build_graph`.
- `tests/test_app.py` runs the real app with Streamlit's `AppTest` and is skipped when `data/processed/` has no Parquet files (run `make all` first). The DOT validity test is skipped when Graphviz `dot` is not installed.
- Write tests for every change, keep the suite and `ruff check` green, and do not change existing assertions during refactoring.

## Gotchas found during the build

- SCADA files: 9 `#` metadata lines, then the column header is itself a `#` comment line; CRLF endings; the static CSV has a UTF-8 BOM.
- The mapping CSV lists `Power` in `kWh`, but the column is `Power (kW)` (10-minute mean power).
- rdflib 7 binds `geo` to GeoSPARQL by default; `new_graph()` forces the project prefixes (`override=True, replace=True`).
- DuckDB returns timestamps in the machine's local time zone; `dashboard.load_series` sets `TimeZone = 'UTC'`.
- plotly 7 `px.scatter_map` does not centre on the data; pass `center=dashboard.map_center(...)`.
- Streamlit `AppTest` cannot drive a datetime slider; set `app.session_state["replay_time"]` instead. Avoid clicking Play in `AppTest` (the `st.rerun` loop runs until timeout).
- `ontology/kelmarsh.ttl` is committed and changes on every `make train` (new `prov:generatedAtTime`); only commit it when its structure changed.
- The 2023 and 2024 SCADA exports (~2.9 GB per turbine file) repeat the year from 1 January many times (~2.17M rows for 52,560 timestamps); repeats are exact or all-NaN copies, and a NaN copy can come first. `load_scada.tidy` keeps the most complete row per timestamp — never switch it back to a plain "keep first".
- Column count differs per year (299 / 303 / 312); only the configured columns are read.
- No row before commissioning (15 April 2016) is `is_normal`, so the commissioning period never reaches training.
- The dashboard power curve samples at most `dashboard.power_curve_max_points` normal rows; with 9 years there are ~370k per turbine.

## Project-specific rules (from spec §8)

- If real data deviates from the spec (file layout, column names, units), adapt the code to match the data and record the change in the "Deviations from spec" section at the end of `README.md` — don't silently special-case it in code without noting it.
- Use type hints and short docstrings; use `logging` for script output (not `print`, except where spec explicitly calls for printed acceptance-criteria output, e.g. row counts, alert summaries).
- Never commit anything under `data/` or `models/` (`.gitignore` covers both).
- Log every change in the `docs/spec.md` §11 change log; commits follow the 50/70 message format, one commit per request.

## Multi-year data (2016–2024)

Implemented per `docs/spec.md` §10.1 (change log: "Feature: multi-year SCADA data"). Years are selected with `config.yaml` `years`; each SCADA zip in `downloads.files` has its own `extract_to` folder. Train on 2016–2021, test on 2022–2024 (`train_test_split.train_end`). To add a year: add its zip entry (name, URL, MD5, `extract_to`), add it to `years`, run `make inspect` to confirm the columns, then `make all`.
