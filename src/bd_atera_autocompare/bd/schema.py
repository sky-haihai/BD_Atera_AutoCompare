from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from ..csv_io import write_csv


BD_CSV_COLUMNS = [
    "Device Name",
    "Company Name",
    "IP Address",
    "Status",
    "Last Seen",
    "BD Row Number",
]


@dataclass(frozen=True)
class BdNormalizedRow:
    device_name: str
    company_name: str
    ip_address: str = ""
    status: str = ""
    last_seen: str = ""
    bd_row_number: str = ""

    def to_csv_row(self) -> dict[str, str]:
        """Return this normalized row using the public BD CSV header names."""
        return {
            "Device Name": self.device_name,
            "Company Name": self.company_name,
            "IP Address": self.ip_address,
            "Status": self.status,
            "Last Seen": self.last_seen,
            "BD Row Number": self.bd_row_number,
        }


class BdProvider(Protocol):
    def get_rows(self) -> list[BdNormalizedRow]:
        """Return normalized Bitdefender rows."""


def write_bd_csv(path: str | Path, rows: Sequence[BdNormalizedRow]) -> None:
    """Write normalized BD rows with the stable module schema."""
    write_csv(path, BD_CSV_COLUMNS, [row.to_csv_row() for row in rows])

