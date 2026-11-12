"""Knowledge of the Greenbyte SCADA export format (file names and headers)."""

import csv
from itertools import islice
from pathlib import Path

COMMENT = "#"
FILE_TYPES = {"Turbine_Data_": "turbine_data", "Status_": "status"}


def classify_file(name: str) -> str:
    """Return the file type from its name: turbine_data, status or other."""
    return next(
        (kind for prefix, kind in FILE_TYPES.items() if name.startswith(prefix)),
        "other",
    )


def group_files(names: list[str]) -> dict[str, list[str]]:
    """Group file names by type, each group sorted."""
    kinds = sorted({classify_file(n) for n in names})
    return {k: sorted(n for n in names if classify_file(n) == k) for k in kinds}


def read_head(path: Path, n: int) -> list[str]:
    """Return the first n lines of a text file, without line endings."""
    with path.open(encoding="utf-8-sig", newline="") as f:
        return [line.rstrip("\r\n") for line in islice(f, n)]


def header_line_index(lines: list[str]) -> int:
    """Index of the column header: the last comment line before the data."""
    first_data = next(
        (i for i, line in enumerate(lines) if not line.startswith(COMMENT)),
        len(lines),
    )
    return first_data - 1


def parse_columns(header_line: str) -> list[str]:
    """Split a (possibly commented) CSV header line into column names."""
    return next(csv.reader([header_line.lstrip(COMMENT).strip()]))
