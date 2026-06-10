from __future__ import annotations

import csv
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from .normalization import clean_display


DEVICE_SORT_COLUMNS = (
    "Device Name",
    "Canonical Device Name",
    "Atera Device Name",
    "BD Device Name",
    "Raw Device Name",
)


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


def display_sort_key(value: Any) -> tuple[int, str, str]:
    text = clean_display(value)
    return (1 if not text else 0, text.casefold(), text)


def first_device_display(row: Mapping[str, Any]) -> str:
    for column in DEVICE_SORT_COLUMNS:
        value = clean_display(row.get(column))
        if value:
            return value
    return ""


def company_device_sort_key(row: Mapping[str, Any]) -> tuple[tuple[int, str, str], tuple[int, str, str]]:
    return display_sort_key(row.get("Company Name")), display_sort_key(first_device_display(row))


def sort_rows_by_company_device(rows: Sequence[Mapping[str, Any]]) -> list[Mapping[str, Any]]:
    return sorted(rows, key=company_device_sort_key)


def write_csv(
    path: str | Path,
    fieldnames: Sequence[str],
    rows: Sequence[Mapping[str, Any]],
    *,
    encoding: str = "utf-8-sig",
    sort_rows: bool = True,
) -> None:
    """Write rows to CSV with a stable column order and create the parent directory."""
    output_path = Path(path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_rows = sort_rows_by_company_device(rows) if sort_rows else rows
    with output_path.open("w", encoding=encoding, newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(output_rows)
