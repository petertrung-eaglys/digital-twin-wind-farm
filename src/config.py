"""Load the project configuration from config.yaml."""

from pathlib import Path
from typing import Any

import yaml

DEFAULT_CONFIG_PATH = Path(__file__).resolve().parent.parent / "config.yaml"


def load_config(path: Path = DEFAULT_CONFIG_PATH) -> dict[str, Any]:
    """Read the YAML config file and return it as a dict."""
    with Path(path).open(encoding="utf-8") as f:
        return yaml.safe_load(f)


def scada_archives(config: dict[str, Any]) -> list[dict[str, str]]:
    """The download entries that are SCADA archives (those with extract_to)."""
    return [f for f in config["downloads"]["files"] if "extract_to" in f]


def scada_dirs(config: dict[str, Any]) -> list[Path]:
    """The raw folders the SCADA archives are unzipped into, in config order."""
    raw = Path(config["paths"]["raw"])
    return [raw / f["extract_to"] for f in scada_archives(config)]
