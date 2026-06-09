from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from .csv_io import write_csv


ATERA_CSV_COLUMNS = [
    "Device Name",
    "Company Name",
    "IP Address",
    "Status",
    "Last Seen",
    "Atera Agent ID",
    "Atera Machine ID",
    "Atera Device GUID",
]


@dataclass(frozen=True)
class AteraNormalizedRow:
    device_name: str
    company_name: str
    ip_address: str = ""
    status: str = ""
    last_seen: str = ""
    atera_agent_id: str = ""
    atera_machine_id: str = ""
    atera_device_guid: str = ""

    def to_csv_row(self) -> dict[str, str]:
        """Return this normalized row using the public Atera CSV header names."""
        return {
            "Device Name": self.device_name,
            "Company Name": self.company_name,
            "IP Address": self.ip_address,
            "Status": self.status,
            "Last Seen": self.last_seen,
            "Atera Agent ID": self.atera_agent_id,
            "Atera Machine ID": self.atera_machine_id,
            "Atera Device GUID": self.atera_device_guid,
        }


class AteraProvider(Protocol):
    def get_rows(self) -> list[AteraNormalizedRow]:
        """Return normalized Atera rows."""


def validate_normalized_rows(rows: Sequence[AteraNormalizedRow]) -> None:
    """Ensure exported Atera rows contain the minimum keys needed for comparison."""
    issues: list[str] = []
    for index, row in enumerate(rows, start=1):
        missing: list[str] = []
        if not row.device_name:
            missing.append("Device Name")
        if not row.company_name:
            missing.append("Company Name")
        if missing:
            issues.append(f"row {index} missing required value(s): {', '.join(missing)}")

    if issues:
        raise ValueError(f"Invalid Atera normalized row(s): {'; '.join(issues)}")


def write_atera_csv(path: str | Path, rows: Sequence[AteraNormalizedRow]) -> None:
    """Validate and write normalized Atera rows with the stable module schema."""
    validate_normalized_rows(rows)
    write_csv(path, ATERA_CSV_COLUMNS, [row.to_csv_row() for row in rows])
