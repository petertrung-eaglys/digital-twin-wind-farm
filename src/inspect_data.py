"""Print the structure of the raw files so config.yaml column names can be set.

Output is printed (not logged) because spec 7.2 asks for printed inspection.
"""

from pathlib import Path

import pandas as pd

from src.config import load_config
from src.scada_format import (
    group_files,
    header_line_index,
    parse_columns,
    read_head,
)

HEAD_LINES = 15
HEADER_SEARCH_LINES = 50


def print_section(title: str) -> None:
    """Print a section heading."""
    print(f"\n=== {title} ===")


def print_file_groups(scada_dir: Path) -> dict[str, list[str]]:
    """Print the SCADA files grouped by type and return the groups."""
    groups = group_files([p.name for p in scada_dir.iterdir() if p.is_file()])
    print_section(f"Files in {scada_dir}")
    for kind, names in groups.items():
        print(f"{kind} ({len(names)}):")
        for name in names:
            print(f"  {name}")
    return groups


def print_turbine_file(path: Path) -> None:
    """Print the raw head and the full column list of one turbine data file."""
    print_section(f"First {HEAD_LINES} raw lines of {path.name}")
    for line in read_head(path, HEAD_LINES):
        print(line[:200] + (" ..." if len(line) > 200 else ""))
    lines = read_head(path, HEADER_SEARCH_LINES)
    index = header_line_index(lines)
    columns = parse_columns(lines[index])
    print_section(f"{len(columns)} columns (header on line {index + 1})")
    for i, column in enumerate(columns):
        print(f"  {i:3d}  {column}")


def print_csv_columns(path: Path) -> None:
    """Print the columns and first rows of a small CSV file."""
    frame = pd.read_csv(path, encoding="utf-8-sig")
    print_section(f"{path.name}: {len(frame)} rows")
    print(f"Columns: {list(frame.columns)}")
    print(frame.head(3).to_string())


def main() -> None:
    """Inspect the SCADA folder and the static and mapping CSVs."""
    config = load_config()
    raw_dir = Path(config["paths"]["raw"])
    groups = print_file_groups(raw_dir / config["downloads"]["scada_dir"])
    first = groups["turbine_data"][0]
    print_turbine_file(raw_dir / config["downloads"]["scada_dir"] / first)
    for f in config["downloads"]["files"]:
        if f["name"].endswith(".csv"):
            print_csv_columns(raw_dir / f["name"])


if __name__ == "__main__":
    main()
