"""Knowledge of the Greenbyte SCADA export format (file names and headers)."""

import csv
import re
from itertools import islice
from pathlib import Path

COMMENT = "#"
FILE_TYPES = {"Turbine_Data_": "turbine_data", "Status_": "status"}
TURBINE_NUMBER_IN_NAME = re.compile(r"Kelmarsh_(\d+)_")


def format_turbine_id(number: int) -> str:
    """Canonical turbine id used everywhere, e.g. 1 -> 'T01'."""
    return f"T{number:02d}"


def turbine_id_from_filename(name: str) -> str:
    """Derive the turbine id from a SCADA file name like '..._Kelmarsh_3_...'."""
    match = TURBINE_NUMBER_IN_NAME.search(name)
    if match is None:
        raise ValueError(f"No turbine number in file name: {name}")
    return format_turbine_id(int(match.group(1)))


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
