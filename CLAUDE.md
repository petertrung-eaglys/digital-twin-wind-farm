# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project state

This repository currently contains only `docs/spec.md` — no `src/`, `app/`, `pyproject.toml`, or `Makefile` exist yet. `docs/spec.md` is the authoritative specification; read it in full before writing any code. Everything below is derived from it.

## Project

One-day proof-of-concept data-driven digital twin for the Kelmarsh wind farm (6x Senvion MM92 turbines), built around a Zenodo SCADA dataset (record 16807551). The PoC favours a complete end-to-end slice over accuracy or completeness.

## Package management: uv only

This project is managed exclusively through `uv` — no `pip`, no `requirements.txt`, no manually created venv.

- Initialise with `uv init`; pin the interpreter with `uv python pin 3.11` (writes `.python-version`).
- Add dependencies with `uv add <package>` — this is the only way new packages enter `pyproject.toml`. Ask before adding any dependency not already listed in spec §4.
- Commit `uv.lock` for reproducible installs.
- Run every script through `uv run`, e.g. `uv run python -m src.<name>`, `uv run streamlit run app/app.py`.

## Commands (as specified, once implemented)

Via the planned `Makefile` (each target shells out through `uv run`):

```
make setup      # uv sync
make download   # fetch raw SCADA data into data/raw/
make inspect    # run inspect_data.py
make data       # load_scada.py + clean.py
make ontology   # build_ontology.py
make train      # train.py
make alerts     # alerts.py
make app        # uv run streamlit run app/app.py
make all        # download through alerts, end to end
```

Each script must also be runnable standalone: `uv run python -m src.<name>`.

## Required build order

The pipeline has a strict dependency order — do not skip ahead:

1. `download.py` — fetch the 3 Zenodo files into `data/raw/`, verify MD5, skip already-downloaded files, unzip the SCADA archive.
2. `inspect_data.py` — **must be run before writing the loader.** Prints raw file structure and real column names. `config.yaml`'s signal column names are placeholders/guesses and must be confirmed from this output before `load_scada.py` is written. Do not guess column names.
3. `load_scada.py` → `clean.py` — produce per-turbine Parquet files in `data/processed/`, then add the `is_normal` cleaning flag and `air_density`.
4. `build_ontology.py` — populate the RDF graph from the static/mapping CSVs and `config.yaml`.
5. `train.py` — one LightGBM power model per turbine, metrics written back into the graph.
6. `alerts.py` — rolling-residual underperformance detection, written back into the graph.
7. `app/app.py` — Streamlit replay dashboard, reads everything from the graph + Parquet.

## Architecture: the RDF graph is the source of structural truth

The central design point (easy to miss without reading multiple files): **`ontology/kelmarsh.ttl` — not `config.yaml` — is what the app and downstream scripts query for structure.** `config.yaml` only holds raw paths, column-name mappings, and numeric thresholds used while *building* the graph.

- `graph_utils.py` is the only place that talks to the graph directly; it exposes `load_graph`, `get_turbines`, `get_sensors`, `get_model_inputs`, `get_alerts`, `add_model`, `add_alert` — all backed by SPARQL queries, not Python dict lookups.
- Every other script (`train.py`, `alerts.py`, `app/app.py`) must go through `graph_utils.py` to discover turbines, sensor→Parquet-path mappings, and model inputs — never read `config.yaml` directly for this. This is what lets the ontology, rather than the config file, define the domain model.
- Raw time-series values live in per-turbine Parquet files (`data/processed/scada_<turbine_id>.parquet`); the graph stores only metadata and relationships (sensors, models, alerts), with `kt:storedIn` pointing at the Parquet path and `kt:scadaColumn`/`kt:signalKey` bridging back to the original SCADA column names.
- `train.py` writes predictions (`expected_power`) back into the turbine's Parquet file and writes a `kt:PowerModel` node (a `prov:Entity`) back into the graph — the graph accumulates provenance across pipeline runs, it isn't regenerated from scratch each time after `build_ontology.py`.
- `alerts.py` reads `expected_power` vs `power` from Parquet, but writes the resulting `kt:Alert` periods back into the graph, linked to both the turbine and the `kt:PowerModel` that raised them.

## Project-specific rules (from spec §8)

- If real data deviates from the spec (file layout, column names, units), adapt the code to match the data and record the change in a "Deviations from spec" section at the end of `README.md` — don't silently special-case it in code without noting it.
- Use type hints and short docstrings; use `logging` for script output (not `print`, except where spec explicitly calls for printed acceptance-criteria output, e.g. row counts, alert summaries).
- Never commit anything under `data/` or `models/` (confirm `.gitignore` covers both before adding files there).
- Each spec component (§7.1–7.10) has its own acceptance criteria — check a component's acceptance criteria before moving on to the next one in the build order above.
