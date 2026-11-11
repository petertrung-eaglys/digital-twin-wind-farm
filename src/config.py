"""Load the project configuration from config.yaml."""

from pathlib import Path
from typing import Any

import yaml

DEFAULT_CONFIG_PATH = Path(__file__).resolve().parent.parent / "config.yaml"


def load_config(path: Path = DEFAULT_CONFIG_PATH) -> dict[str, Any]:
    """Read the YAML config file and return it as a dict."""
    with Path(path).open(encoding="utf-8") as f:
        return yaml.safe_load(f)
