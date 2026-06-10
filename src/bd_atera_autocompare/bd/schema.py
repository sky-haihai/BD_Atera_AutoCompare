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
    "BD Endpoint ID",
    "BD Company ID",
    "Parent ID",
    "Network Item Type",
    "Is In Deleted Folder",
    "Label",
    "FQDN",
    "Group ID",
    "MAC Addresses",
    "SSID",
    "Is Managed",
    "Managed With BEST",
    "Machine Type",
    "Operating System Version",
    "Is Container Host",
    "Managed Exchange Server",
    "Managed Relay",
    "Security Server",
    "Policy ID",
    "Policy Name",
    "Policy Applied",
    "Moving State",
    "Destination Company Name",
    "Product Outdated",
    "Last Successful Scan Name",
    "Last Successful Scan Date",
    "Modules",
]


@dataclass(frozen=True)
class BdNormalizedRow:
    device_name: str
    company_name: str
    ip_address: str = ""
    status: str = ""
    last_seen: str = ""
    bd_row_number: str = ""
    bd_endpoint_id: str = ""
    bd_company_id: str = ""
    parent_id: str = ""
    network_item_type: str = ""
    is_in_deleted_folder: str = ""
    label: str = ""
    fqdn: str = ""
    group_id: str = ""
    mac_addresses: str = ""
    ssid: str = ""
    is_managed: str = ""
    managed_with_best: str = ""
    machine_type: str = ""
    operating_system_version: str = ""
    is_container_host: str = ""
    managed_exchange_server: str = ""
    managed_relay: str = ""
    security_server: str = ""
    policy_id: str = ""
    policy_name: str = ""
    policy_applied: str = ""
    moving_state: str = ""
    destination_company_name: str = ""
    product_outdated: str = ""
    last_successful_scan_name: str = ""
    last_successful_scan_date: str = ""
    modules: str = ""

    def to_csv_row(self) -> dict[str, str]:
        """Return this normalized row using the public BD CSV header names."""
        return {
            "Device Name": self.device_name,
            "Company Name": self.company_name,
            "IP Address": self.ip_address,
            "Status": self.status,
            "Last Seen": self.last_seen,
            "BD Row Number": self.bd_row_number,
            "BD Endpoint ID": self.bd_endpoint_id,
            "BD Company ID": self.bd_company_id,
            "Parent ID": self.parent_id,
            "Network Item Type": self.network_item_type,
            "Is In Deleted Folder": self.is_in_deleted_folder,
            "Label": self.label,
            "FQDN": self.fqdn,
            "Group ID": self.group_id,
            "MAC Addresses": self.mac_addresses,
            "SSID": self.ssid,
            "Is Managed": self.is_managed,
            "Managed With BEST": self.managed_with_best,
            "Machine Type": self.machine_type,
            "Operating System Version": self.operating_system_version,
            "Is Container Host": self.is_container_host,
            "Managed Exchange Server": self.managed_exchange_server,
            "Managed Relay": self.managed_relay,
            "Security Server": self.security_server,
            "Policy ID": self.policy_id,
            "Policy Name": self.policy_name,
            "Policy Applied": self.policy_applied,
            "Moving State": self.moving_state,
            "Destination Company Name": self.destination_company_name,
            "Product Outdated": self.product_outdated,
            "Last Successful Scan Name": self.last_successful_scan_name,
            "Last Successful Scan Date": self.last_successful_scan_date,
            "Modules": self.modules,
        }


class BdProvider(Protocol):
    def get_rows(self) -> list[BdNormalizedRow]:
        """Return normalized Bitdefender rows."""


def write_bd_csv(path: str | Path, rows: Sequence[BdNormalizedRow]) -> None:
    """Write normalized BD rows with the stable module schema."""
    write_csv(path, BD_CSV_COLUMNS, [row.to_csv_row() for row in rows])
