.PHONY: setup download inspect data ontology train alerts app all test lint

setup:
	uv sync

download:
	uv run python -m src.download

inspect:
	uv run python -m src.inspect_data

data:
	uv run python -m src.load_scada
	uv run python -m src.clean

ontology:
	uv run python -m src.build_ontology

train:
	uv run python -m src.train

alerts:
	uv run python -m src.alerts

app:
	uv run streamlit run app/app.py

all: download data ontology train alerts

test:
	uv run pytest

lint:
	uv run ruff check .
