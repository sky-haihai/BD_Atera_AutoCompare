from __future__ import annotations

import csv
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any


def require_headers(
    fieldnames: Sequence[str] | None,
    required_headers: Sequence[str],
    source: str | Path,
) -> None:
    """Validate that a CSV-like field list contains all required headers."""
    actual = set(fieldnames or [])
    missing = [header for header in required_headers if header not in actual]
    if missing:
        raise ValueError(f"{source} is missing required header(s): {', '.join(missing)}")


def write_csv(
    path: str | Path,
    fieldnames: Sequence[str],
    rows: Sequence[Mapping[str, Any]],
    *,
    encoding: str = "utf-8-sig",
) -> None:
    """Write rows to CSV with a stable column order and create the parent directory."""
    output_path = Path(path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding=encoding, newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)
