from __future__ import annotations

import argparse
import csv
import difflib
import re
import sys
from collections import Counter, defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from ..atera.schema import ATERA_CSV_COLUMNS
from ..csv_io import require_headers, write_csv
from ..normalization import clean_display


DEFAULT_ATERA_CSV_PATH = Path("output/atera_agents.csv")
DEFAULT_BD_CSV_PATH = Path("output/bd_endpoint_status.csv")
DEFAULT_OUTPUT_PATH = Path("output/mismatch.csv")
DEFAULT_DUPLICATES_OUTPUT_PATH = Path("output/duplicates.csv")
DEFAULT_COMPANY_ALIASES_PATH = Path("config/company_aliases.csv")
DEFAULT_DEVICE_ALIASES_PATH = Path("config/device_aliases.csv")
DEFAULT_EXCLUDE_COMPANY_PATH = Path("config/exclude_company.csv")
DEFAULT_LOCAL_TIME_ZONE = ZoneInfo("America/Edmonton")
NAME_SIMILARITY_THRESHOLD = 0.80
OFFLINE_LAST_SEEN_WINDOW = timedelta(minutes=60)

BD_COMPARE_REQUIRED_COLUMNS = [
    "Device Name",
    "Company Name",
    "IP Address",
    "Status",
]
BD_ENDPOINT_NETWORK_ITEM_TYPES = {"5", "6", "7"}

COMPANY_ALIAS_COLUMNS = [
    "Atera Company Name",
    "BD Company Name",
]

DEVICE_ALIAS_COLUMNS = [
    "Company Name",
    "Raw Device Name",
    "Canonical Device Name",
]

EXCLUDE_COMPANY_COLUMNS = [
    "Company Name",
    "ExcludeSoftware",
]

SOFTWARE_ATERA = "atera"
SOFTWARE_BD = "bd"
EXCLUDE_SOFTWARE_ALIASES = {
    "atera": SOFTWARE_ATERA,
    "atera agent": SOFTWARE_ATERA,
    "bd": SOFTWARE_BD,
    "bitdefender": SOFTWARE_BD,
    "bitdefender endpoint protection": SOFTWARE_BD,
}

COMPARE_REPORT_COLUMNS = [
    "Atera Device Name",
    "BD Device Name",
    "Canonical Device Name",
    "Company Name",
    "Missing Software",
    "Issue Type",
    "Match Evidence",
    "Name Similarity",
    "Atera IPv4",
    "BD IPv4",
    "Atera Status",
    "BD Status",
    "Atera Last Seen",
    "BD Last Seen",
    "Atera Count",
    "BD Count",
    "Atera Agent IDs",
    "Atera Machine IDs",
    "Atera Device GUIDs",
    "BD Row Numbers",
    "BD Endpoint IDs",
    "BD Company IDs",
    "BD Parent IDs",
    "BD Network Item Types",
    "Atera MAC Addresses",
    "BD MAC Addresses",
    "BD Modules",
    "BD Last Successful Scan Date",
    "Alias Applied",
    "Notes",
]

DUPLICATE_REPORT_COLUMNS = [
    "Source",
    "Duplicate Key",
    "Company Name",
    "Canonical Device Name",
    "Raw Device Name",
    "Atera Count",
    "BD Count",
    "Status",
    "Last Seen",
    "IPv4",
    "MAC Addresses",
    "Alias Applied",
    "Atera Agent ID",
    "Atera Machine ID",
    "Atera Device GUID",
    "BD Row Number",
    "BD Endpoint ID",
    "BD Company ID",
    "BD Parent ID",
    "BD Network Item Type",
    "BD Managed With BEST",
    "BD Modules",
    "BD Last Successful Scan Date",
    "Source CSV Row",
    "Duplicate Evidence",
    "Notes",
]

OFFLINE_STATUS_KEYS = {
    "false",
    "0",
    "no",
    "offline",
    "disconnected",
    "inactive",
    "not connected",
    "not-connected",
}

IPV4_PATTERN = re.compile(
    r"(?<![\d.])"
    r"(?:25[0-5]|2[0-4]\d|1?\d?\d)"
    r"(?:\.(?:25[0-5]|2[0-4]\d|1?\d?\d)){3}"
    r"(?![\d.])"
)

MAC_PATTERN = re.compile(r"(?i)(?:[0-9a-f]{2}[:-]){5}[0-9a-f]{2}|(?<![0-9a-f])[0-9a-f]{12}(?![0-9a-f])")


@dataclass(frozen=True)
class EndpointRecord:
    source: str
    raw_device: str
    canonical_device: str
    raw_company: str
    company: str
    ip_raw: str = ""
    ipv4s: tuple[str, ...] = ()
    status_raw: str = ""
    offline: bool = False
    last_seen_raw: str = ""
    last_seen: datetime | None = None
    last_seen_has_time: bool = False
    bd_row_number: str = ""
    bd_endpoint_id: str = ""
    bd_company_id: str = ""
    bd_parent_id: str = ""
    bd_network_item_type: str = ""
    bd_managed_with_best: str = ""
    bd_modules: str = ""
    bd_last_successful_scan_date: str = ""
    bd_is_in_deleted_folder: bool = False
    atera_agent_id: str = ""
    atera_machine_id: str = ""
    atera_device_guid: str = ""
    mac_addresses: tuple[str, ...] = ()
    alias_applied: bool = False
    notes: tuple[str, ...] = ()
    line_number: int = 0


@dataclass(frozen=True)
class PotentialCandidate:
    atera: EndpointRecord
    bd: EndpointRecord
    similarity: float
    evidence: str


@dataclass(frozen=True)
class CompareOutputs:
    exception_rows: list[dict[str, str]]
    duplicate_rows: list[dict[str, str]]


def normalize_key(value: object) -> str:
    """Return the comparison key form used for companies and devices."""
    return clean_display(value).casefold()


def unique_display_values(values: Sequence[object]) -> list[str]:
    """Return nonblank display values with case-insensitive duplicates removed."""
    seen: set[str] = set()
    output: list[str] = []
    for value in values:
        text = clean_display(value)
        if not text:
            continue
        key = text.casefold()
        if key in seen:
            continue
        seen.add(key)
        output.append(text)
    return output


def join_unique(values: Sequence[object]) -> str:
    return "; ".join(unique_display_values(values))


def extract_ipv4s(value: object) -> tuple[str, ...]:
    """Extract IPv4 addresses from a normalized CSV field and ignore IPv6."""
    text = clean_display(value)
    if not text:
        return ()

    seen: set[str] = set()
    output: list[str] = []
    for match in IPV4_PATTERN.finditer(text):
        candidate = match.group(0)
        if candidate in seen:
            continue
        seen.add(candidate)
        output.append(candidate)
    return tuple(output)


def extract_mac_addresses(value: object) -> tuple[str, ...]:
    """Extract and normalize MAC addresses from normalized CSV fields."""
    text = clean_display(value)
    if not text:
        return ()

    seen: set[str] = set()
    output: list[str] = []
    for match in MAC_PATTERN.finditer(text):
        compact = re.sub(r"[^0-9a-fA-F]", "", match.group(0)).upper()
        normalized = ":".join(compact[index : index + 2] for index in range(0, 12, 2))
        if normalized in seen:
            continue
        seen.add(normalized)
        output.append(normalized)
    return tuple(output)


def is_offline_status(value: object) -> bool:
    return normalize_key(value) in OFFLINE_STATUS_KEYS


def is_truthy_display(value: object) -> bool:
    return normalize_key(value) in {"true", "1", "yes", "y"}


def is_falsey_display(value: object) -> bool:
    return normalize_key(value) in {"false", "0", "no", "n"}


def bd_missing_best(record: EndpointRecord) -> bool:
    """Return whether a BD API row proves the endpoint does not have BEST."""
    if record.source != "bd":
        return False

    if is_falsey_display(record.bd_managed_with_best):
        return True
    if is_truthy_display(record.bd_managed_with_best):
        return False

    return normalize_key(record.status_raw) in {"no best", "unmanaged"}


def bd_in_deleted_folder(record: EndpointRecord) -> bool:
    """Return whether a BD row came from GravityZone's Deleted folder."""
    return record.source == "bd" and record.bd_is_in_deleted_folder


def is_non_endpoint_bd_inventory_row(record: EndpointRecord) -> bool:
    if record.source != "bd" or not record.bd_network_item_type:
        return False
    return record.bd_network_item_type not in BD_ENDPOINT_NETWORK_ITEM_TYPES


def parse_last_seen(value: object) -> tuple[datetime | None, bool, str]:
    """Parse a Last Seen value, assuming Edmonton time when no timezone is present."""
    text = clean_display(value)
    if not text:
        return None, False, ""

    iso_text = text[:-1] + "+00:00" if text.endswith("Z") else text
    try:
        parsed = datetime.fromisoformat(iso_text)
        has_time = bool(re.search(r"\d{1,2}:\d{2}", text))
        return ensure_timezone(parsed), has_time, ""
    except ValueError:
        pass

    time_formats = (
        "%d %B %Y, %H:%M:%S",
        "%d %b %Y, %H:%M:%S",
        "%Y-%m-%d %H:%M:%S",
        "%m/%d/%Y %H:%M:%S",
    )
    for timestamp_format in time_formats:
        try:
            return ensure_timezone(datetime.strptime(text, timestamp_format)), True, ""
        except ValueError:
            continue

    date_formats = (
        "%Y-%m-%d",
        "%d %B %Y",
        "%d %b %Y",
        "%m/%d/%Y",
    )
    for date_format in date_formats:
        try:
            return ensure_timezone(datetime.strptime(text, date_format)), False, ""
        except ValueError:
            continue

    return None, False, f"Unparseable Last Seen: {text}"


def ensure_timezone(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=DEFAULT_LOCAL_TIME_ZONE)
    return value


def blank_report_row() -> dict[str, str]:
    return {column: "" for column in COMPARE_REPORT_COLUMNS}


def blank_duplicate_row() -> dict[str, str]:
    return {column: "" for column in DUPLICATE_REPORT_COLUMNS}


def source_display(source: str) -> str:
    if normalize_key(source) == "bd":
        return "BD"
    return source.title()


def build_report_row(
    *,
    issue_type: str,
    atera_records: Sequence[EndpointRecord] = (),
    bd_records: Sequence[EndpointRecord] = (),
    missing_software: str = "",
    match_evidence: str = "",
    name_similarity: str = "",
    notes: Sequence[str] = (),
) -> dict[str, str]:
    """Build one fixed-schema mismatch report row."""
    row = blank_report_row()
    all_records = [*atera_records, *bd_records]
    record_notes = [note for record in all_records for note in record.notes]

    row.update(
        {
            "Atera Device Name": join_unique([record.raw_device for record in atera_records]),
            "BD Device Name": join_unique([record.raw_device for record in bd_records]),
            "Canonical Device Name": join_unique([record.canonical_device for record in all_records]),
            "Company Name": join_unique([record.company for record in all_records]),
            "Missing Software": missing_software,
            "Issue Type": issue_type,
            "Match Evidence": match_evidence,
            "Name Similarity": name_similarity,
            "Atera IPv4": join_unique([ip for record in atera_records for ip in record.ipv4s]),
            "BD IPv4": join_unique([ip for record in bd_records for ip in record.ipv4s]),
            "Atera Status": join_unique([record.status_raw for record in atera_records]),
            "BD Status": join_unique([record.status_raw for record in bd_records]),
            "Atera Last Seen": join_unique([record.last_seen_raw for record in atera_records]),
            "BD Last Seen": join_unique([record.last_seen_raw for record in bd_records]),
            "Atera Count": str(len(atera_records)),
            "BD Count": str(len(bd_records)),
            "Atera Agent IDs": join_unique([record.atera_agent_id for record in atera_records]),
            "Atera Machine IDs": join_unique([record.atera_machine_id for record in atera_records]),
            "Atera Device GUIDs": join_unique([record.atera_device_guid for record in atera_records]),
            "BD Row Numbers": join_unique([record.bd_row_number for record in bd_records]),
            "BD Endpoint IDs": join_unique([record.bd_endpoint_id for record in bd_records]),
            "BD Company IDs": join_unique([record.bd_company_id for record in bd_records]),
            "BD Parent IDs": join_unique([record.bd_parent_id for record in bd_records]),
            "BD Network Item Types": join_unique([record.bd_network_item_type for record in bd_records]),
            "Atera MAC Addresses": join_unique([mac for record in atera_records for mac in record.mac_addresses]),
            "BD MAC Addresses": join_unique([mac for record in bd_records for mac in record.mac_addresses]),
            "BD Modules": join_unique([record.bd_modules for record in bd_records]),
            "BD Last Successful Scan Date": join_unique(
                [record.bd_last_successful_scan_date for record in bd_records]
            ),
            "Alias Applied": "Yes" if any(record.alias_applied for record in all_records) else "No",
            "Notes": join_unique([*record_notes, *notes]),
        }
    )
    return row


def build_duplicate_detail_rows(
    *,
    atera_records: Sequence[EndpointRecord],
    bd_records: Sequence[EndpointRecord],
    evidence: str,
) -> list[dict[str, str]]:
    all_records = [*atera_records, *bd_records]
    company = join_unique([record.company for record in all_records])
    canonical_device = join_unique([record.canonical_device for record in all_records])
    duplicate_key = " | ".join(value for value in (company, canonical_device) if value)
    atera_count = str(len(atera_records))
    bd_count = str(len(bd_records))
    rows: list[dict[str, str]] = []

    for record in all_records:
        row = blank_duplicate_row()
        row.update(
            {
                "Source": source_display(record.source),
                "Duplicate Key": duplicate_key,
                "Company Name": record.company,
                "Canonical Device Name": record.canonical_device,
                "Raw Device Name": record.raw_device,
                "Atera Count": atera_count,
                "BD Count": bd_count,
                "Status": record.status_raw,
                "Last Seen": record.last_seen_raw,
                "IPv4": join_unique(record.ipv4s),
                "MAC Addresses": join_unique(record.mac_addresses),
                "Alias Applied": "Yes" if record.alias_applied else "No",
                "Atera Agent ID": record.atera_agent_id,
                "Atera Machine ID": record.atera_machine_id,
                "Atera Device GUID": record.atera_device_guid,
                "BD Row Number": record.bd_row_number,
                "BD Endpoint ID": record.bd_endpoint_id,
                "BD Company ID": record.bd_company_id,
                "BD Parent ID": record.bd_parent_id,
                "BD Network Item Type": record.bd_network_item_type,
                "BD Managed With BEST": record.bd_managed_with_best,
                "BD Modules": record.bd_modules,
                "BD Last Successful Scan Date": record.bd_last_successful_scan_date,
                "Source CSV Row": str(record.line_number),
                "Duplicate Evidence": evidence,
                "Notes": join_unique(record.notes),
            }
        )
        rows.append(row)

    return rows


def build_data_quality_row(
    *,
    notes: str,
    company: object = "",
    atera_device: object = "",
    bd_device: object = "",
    canonical_device: object = "",
    atera_agent_id: object = "",
    atera_machine_id: object = "",
    atera_device_guid: object = "",
    bd_row_number: object = "",
    bd_endpoint_id: object = "",
    bd_company_id: object = "",
    bd_parent_id: object = "",
    bd_network_item_type: object = "",
    bd_modules: object = "",
    bd_last_successful_scan_date: object = "",
) -> dict[str, str]:
    row = blank_report_row()
    row.update(
        {
            "Atera Device Name": clean_display(atera_device),
            "BD Device Name": clean_display(bd_device),
            "Canonical Device Name": clean_display(canonical_device),
            "Company Name": clean_display(company),
            "Issue Type": "Data Quality Review",
            "Atera Count": "1" if atera_device or atera_agent_id or atera_machine_id or atera_device_guid else "0",
            "BD Count": "1" if bd_device or bd_row_number or bd_endpoint_id else "0",
            "Atera Agent IDs": clean_display(atera_agent_id),
            "Atera Machine IDs": clean_display(atera_machine_id),
            "Atera Device GUIDs": clean_display(atera_device_guid),
            "BD Row Numbers": clean_display(bd_row_number),
            "BD Endpoint IDs": clean_display(bd_endpoint_id),
            "BD Company IDs": clean_display(bd_company_id),
            "BD Parent IDs": clean_display(bd_parent_id),
            "BD Network Item Types": clean_display(bd_network_item_type),
            "BD Modules": clean_display(bd_modules),
            "BD Last Successful Scan Date": clean_display(bd_last_successful_scan_date),
            "Alias Applied": "No",
            "Notes": clean_display(notes),
        }
    )
    return row


def read_csv_rows(path: str | Path, required_headers: Sequence[str]) -> list[tuple[dict[str, str], int]]:
    csv_path = Path(path)
    with csv_path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        require_headers(reader.fieldnames, required_headers, csv_path)
        return [(dict(row), reader.line_num) for row in reader]


def read_company_aliases(path: str | Path | None) -> tuple[dict[str, str], list[dict[str, str]]]:
    if path is None:
        return {}, []

    alias_path = Path(path)
    if not alias_path.exists():
        return {}, []

    aliases: dict[str, str] = {}
    data_quality_rows: list[dict[str, str]] = []
    for row, line_number in read_csv_rows(alias_path, COMPANY_ALIAS_COLUMNS):
        atera_company = clean_display(row.get("Atera Company Name"))
        bd_company = clean_display(row.get("BD Company Name"))
        missing = []
        if not atera_company:
            missing.append("Atera Company Name")
        if not bd_company:
            missing.append("BD Company Name")
        if missing:
            data_quality_rows.append(
                build_data_quality_row(
                    company=bd_company or atera_company,
                    notes=f"{alias_path} row {line_number} missing required value(s): {', '.join(missing)}",
                )
            )
            continue
        aliases[normalize_key(atera_company)] = bd_company
    return aliases, data_quality_rows


def canonicalize_company_for_alias_file(company: str, company_aliases: Mapping[str, str]) -> str:
    return company_aliases.get(normalize_key(company), company)


def read_device_aliases(
    path: str | Path | None,
    company_aliases: Mapping[str, str],
) -> tuple[dict[tuple[str, str], str], list[dict[str, str]]]:
    if path is None:
        return {}, []

    alias_path = Path(path)
    if not alias_path.exists():
        return {}, []

    aliases: dict[tuple[str, str], str] = {}
    data_quality_rows: list[dict[str, str]] = []
    for row, line_number in read_csv_rows(alias_path, DEVICE_ALIAS_COLUMNS):
        company = clean_display(row.get("Company Name"))
        raw_device = clean_display(row.get("Raw Device Name"))
        canonical_device = clean_display(row.get("Canonical Device Name"))
        missing = []
        if not company:
            missing.append("Company Name")
        if not raw_device:
            missing.append("Raw Device Name")
        if not canonical_device:
            missing.append("Canonical Device Name")
        if missing:
            data_quality_rows.append(
                build_data_quality_row(
                    company=company,
                    canonical_device=canonical_device or raw_device,
                    notes=f"{alias_path} row {line_number} missing required value(s): {', '.join(missing)}",
                )
            )
            continue

        canonical_company = canonicalize_company_for_alias_file(company, company_aliases)
        aliases[(normalize_key(canonical_company), normalize_key(raw_device))] = canonical_device
    return aliases, data_quality_rows


def normalize_exclude_software(value: object) -> str | None:
    return EXCLUDE_SOFTWARE_ALIASES.get(normalize_key(value))


def read_exclude_company(
    path: str | Path | None,
    company_aliases: Mapping[str, str],
) -> tuple[dict[str, set[str]], list[dict[str, str]]]:
    if path is None:
        return {}, []

    exclude_path = Path(path)
    if not exclude_path.exists():
        return {}, []

    excluded: dict[str, set[str]] = defaultdict(set)
    data_quality_rows: list[dict[str, str]] = []
    for row, line_number in read_csv_rows(exclude_path, EXCLUDE_COMPANY_COLUMNS):
        company = clean_display(row.get("Company Name"))
        exclude_software = clean_display(row.get("ExcludeSoftware"))
        missing = []
        if not company:
            missing.append("Company Name")
        if not exclude_software:
            missing.append("ExcludeSoftware")

        software_key = normalize_exclude_software(exclude_software)
        invalid_software = bool(exclude_software and software_key is None)
        if missing or invalid_software:
            issues = []
            if missing:
                issues.append(f"missing required value(s): {', '.join(missing)}")
            if invalid_software:
                issues.append("ExcludeSoftware must be Atera or BD")
            data_quality_rows.append(
                build_data_quality_row(
                    company=canonicalize_company_for_alias_file(company, company_aliases) if company else "",
                    notes=f"{exclude_path} row {line_number} {'; '.join(issues)}",
                )
            )
            continue

        canonical_company = canonicalize_company_for_alias_file(company, company_aliases)
        excluded[normalize_key(canonical_company)].add(software_key)
    return dict(excluded), data_quality_rows


def company_excludes_software(
    company: str,
    software: str,
    excluded_software_by_company: Mapping[str, set[str]],
) -> bool:
    return software in excluded_software_by_company.get(normalize_key(company), set())


def any_record_excludes_software(
    records: Sequence[EndpointRecord],
    software: str,
    excluded_software_by_company: Mapping[str, set[str]],
) -> bool:
    return any(company_excludes_software(record.company, software, excluded_software_by_company) for record in records)


def canonical_company_for_record(source: str, raw_company: str, company_aliases: Mapping[str, str]) -> tuple[str, bool]:
    if source != "atera":
        return raw_company, False

    alias = company_aliases.get(normalize_key(raw_company))
    if alias is None:
        return raw_company, False
    return alias, True


def canonical_device_for_record(
    raw_device: str,
    company: str,
    device_aliases: Mapping[tuple[str, str], str],
) -> tuple[str, bool]:
    alias = device_aliases.get((normalize_key(company), normalize_key(raw_device)))
    if alias is None:
        return raw_device, False
    return alias, True


def make_record(
    source: str,
    row: Mapping[str, object],
    line_number: int,
    company_aliases: Mapping[str, str],
    device_aliases: Mapping[tuple[str, str], str],
) -> EndpointRecord:
    raw_company = clean_display(row.get("Company Name"))
    raw_device = clean_display(row.get("Device Name"))
    company, company_alias_applied = canonical_company_for_record(source, raw_company, company_aliases)
    canonical_device, device_alias_applied = canonical_device_for_record(raw_device, company, device_aliases)
    last_seen, last_seen_has_time, last_seen_note = parse_last_seen(row.get("Last Seen"))
    status_raw = clean_display(row.get("Status"))
    notes = (last_seen_note,) if last_seen_note else ()

    if source == "atera":
        return EndpointRecord(
            source=source,
            raw_device=raw_device,
            canonical_device=canonical_device,
            raw_company=raw_company,
            company=company,
            ip_raw=clean_display(row.get("IP Address")),
            ipv4s=extract_ipv4s(row.get("IP Address")),
            status_raw=status_raw,
            offline=is_offline_status(status_raw),
            last_seen_raw=clean_display(row.get("Last Seen")),
            last_seen=last_seen,
            last_seen_has_time=last_seen_has_time,
            atera_agent_id=clean_display(row.get("Atera Agent ID")),
            atera_machine_id=clean_display(row.get("Atera Machine ID")),
            atera_device_guid=clean_display(row.get("Atera Device GUID")),
            mac_addresses=extract_mac_addresses(row.get("MAC Addresses")),
            alias_applied=company_alias_applied or device_alias_applied,
            notes=notes,
            line_number=line_number,
        )

    return EndpointRecord(
        source=source,
        raw_device=raw_device,
        canonical_device=canonical_device,
        raw_company=raw_company,
        company=company,
        ip_raw=clean_display(row.get("IP Address")),
        ipv4s=extract_ipv4s(row.get("IP Address")),
        status_raw=status_raw,
        offline=is_offline_status(status_raw),
        last_seen_raw=clean_display(row.get("Last Seen")),
        last_seen=last_seen,
        last_seen_has_time=last_seen_has_time,
        bd_row_number=clean_display(row.get("BD Row Number")),
        bd_endpoint_id=clean_display(row.get("BD Endpoint ID")),
        bd_company_id=clean_display(row.get("BD Company ID")),
        bd_parent_id=clean_display(row.get("Parent ID")),
        bd_network_item_type=clean_display(row.get("Network Item Type")),
        bd_managed_with_best=clean_display(row.get("Managed With BEST")),
        bd_modules=clean_display(row.get("Modules")),
        bd_last_successful_scan_date=clean_display(row.get("Last Successful Scan Date")),
        bd_is_in_deleted_folder=is_truthy_display(row.get("Is In Deleted Folder")),
        mac_addresses=extract_mac_addresses(row.get("MAC Addresses")),
        alias_applied=company_alias_applied or device_alias_applied,
        notes=notes,
        line_number=line_number,
    )


def validate_record(record: EndpointRecord) -> list[str]:
    missing: list[str] = []
    if not record.raw_device:
        missing.append("Device Name")
    if not record.raw_company:
        missing.append("Company Name")
    if is_non_endpoint_bd_inventory_row(record):
        missing.append(
            f"Network Item Type must be endpoint type {', '.join(sorted(BD_ENDPOINT_NETWORK_ITEM_TYPES))}"
        )
    return missing


def build_record_data_quality_row(record: EndpointRecord, missing: Sequence[str]) -> dict[str, str]:
    notes = f"{record.source.title()} CSV row {record.line_number} data quality issue(s): {', '.join(missing)}"
    if record.source == "atera":
        return build_data_quality_row(
            company=record.company or record.raw_company,
            atera_device=record.raw_device,
            canonical_device=record.canonical_device,
            atera_agent_id=record.atera_agent_id,
            atera_machine_id=record.atera_machine_id,
            atera_device_guid=record.atera_device_guid,
            notes=notes,
        )

    return build_data_quality_row(
        company=record.company or record.raw_company,
        bd_device=record.raw_device,
        canonical_device=record.canonical_device,
        bd_row_number=record.bd_row_number,
        bd_endpoint_id=record.bd_endpoint_id,
        bd_company_id=record.bd_company_id,
        bd_parent_id=record.bd_parent_id,
        bd_network_item_type=record.bd_network_item_type,
        bd_modules=record.bd_modules,
        bd_last_successful_scan_date=record.bd_last_successful_scan_date,
        notes=notes,
    )


def build_records(
    source: str,
    rows: Sequence[tuple[Mapping[str, object], int]],
    company_aliases: Mapping[str, str],
    device_aliases: Mapping[tuple[str, str], str],
) -> tuple[list[EndpointRecord], list[dict[str, str]]]:
    records: list[EndpointRecord] = []
    data_quality_rows: list[dict[str, str]] = []
    for row, line_number in rows:
        record = make_record(source, row, line_number, company_aliases, device_aliases)
        if bd_in_deleted_folder(record):
            continue
        missing = validate_record(record)
        if missing:
            data_quality_rows.append(build_record_data_quality_row(record, missing))
            continue
        records.append(record)
    return records, data_quality_rows


def primary_key(record: EndpointRecord) -> tuple[str, str]:
    return normalize_key(record.company), normalize_key(record.canonical_device)


def group_records(records: Sequence[EndpointRecord]) -> dict[tuple[str, str], list[EndpointRecord]]:
    grouped: dict[tuple[str, str], list[EndpointRecord]] = defaultdict(list)
    for record in records:
        grouped[primary_key(record)].append(record)
    return dict(grouped)


def ordered_group_keys(
    atera_groups: Mapping[tuple[str, str], Sequence[EndpointRecord]],
    bd_groups: Mapping[tuple[str, str], Sequence[EndpointRecord]],
) -> list[tuple[str, str]]:
    keys: list[tuple[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for key in [*atera_groups.keys(), *bd_groups.keys()]:
        if key in seen:
            continue
        seen.add(key)
        keys.append(key)
    return keys


def classify_primary_matches(
    atera_records: Sequence[EndpointRecord],
    bd_records: Sequence[EndpointRecord],
    excluded_software_by_company: Mapping[str, set[str]],
) -> tuple[list[dict[str, str]], set[EndpointRecord], set[EndpointRecord]]:
    atera_groups = group_records(atera_records)
    bd_groups = group_records(bd_records)
    rows: list[dict[str, str]] = []
    handled_atera: set[EndpointRecord] = set()
    handled_bd: set[EndpointRecord] = set()

    for key in ordered_group_keys(atera_groups, bd_groups):
        atera_group = atera_groups.get(key, [])
        bd_group = bd_groups.get(key, [])
        is_exact_single_match = len(atera_group) == 1 and len(bd_group) == 1
        has_duplicate = len(atera_group) > 1 or len(bd_group) > 1

        if is_exact_single_match:
            if bd_missing_best(bd_group[0]) and not any_record_excludes_software(
                atera_group,
                SOFTWARE_BD,
                excluded_software_by_company,
            ):
                rows.append(
                    build_report_row(
                        issue_type="Missing BD",
                        atera_records=atera_group,
                        bd_records=bd_group,
                        missing_software="Bitdefender Endpoint Protection",
                        match_evidence="BD endpoint is not managed with BEST",
                    )
                )
            handled_atera.update(atera_group)
            handled_bd.update(bd_group)
            continue

        if has_duplicate:
            rows.append(
                build_report_row(
                    issue_type="Duplicate Manual Review",
                    atera_records=atera_group,
                    bd_records=bd_group,
                    match_evidence="Duplicate canonical company + device key",
                    notes=("Duplicate detected after aliasing.",),
                )
            )
            handled_atera.update(atera_group)
            handled_bd.update(bd_group)

    return rows, handled_atera, handled_bd


def find_duplicate_detail_rows(
    atera_records: Sequence[EndpointRecord],
    bd_records: Sequence[EndpointRecord],
) -> list[dict[str, str]]:
    atera_groups = group_records(atera_records)
    bd_groups = group_records(bd_records)
    rows: list[dict[str, str]] = []
    evidence = "Duplicate canonical company + device key"

    for key in ordered_group_keys(atera_groups, bd_groups):
        atera_group = atera_groups.get(key, [])
        bd_group = bd_groups.get(key, [])
        if len(atera_group) <= 1 and len(bd_group) <= 1:
            continue
        rows.extend(
            build_duplicate_detail_rows(
                atera_records=atera_group,
                bd_records=bd_group,
                evidence=evidence,
            )
        )

    return rows


def name_similarity(atera: EndpointRecord, bd: EndpointRecord) -> float:
    return difflib.SequenceMatcher(
        None,
        normalize_key(atera.canonical_device),
        normalize_key(bd.canonical_device),
    ).ratio()


def offline_last_seen_evidence(atera: EndpointRecord, bd: EndpointRecord) -> str:
    if not (atera.offline and bd.offline):
        return ""
    if not (atera.last_seen and bd.last_seen and atera.last_seen_has_time and bd.last_seen_has_time):
        return ""

    atera_local = atera.last_seen.astimezone(DEFAULT_LOCAL_TIME_ZONE)
    bd_local = bd.last_seen.astimezone(DEFAULT_LOCAL_TIME_ZONE)
    if atera_local.date() != bd_local.date():
        return ""

    delta = abs(atera_local - bd_local)
    if delta > OFFLINE_LAST_SEEN_WINDOW:
        return ""

    minutes = round(delta.total_seconds() / 60)
    return f"Offline Last Seen within {minutes} minute(s)"


def potential_match_evidence(atera: EndpointRecord, bd: EndpointRecord) -> str:
    overlapping_macs = sorted(set(atera.mac_addresses) & set(bd.mac_addresses))
    if overlapping_macs:
        return f"MAC overlap: {'; '.join(overlapping_macs)}"

    overlapping_ipv4s = sorted(set(atera.ipv4s) & set(bd.ipv4s))
    if overlapping_ipv4s:
        return f"IPv4 overlap: {'; '.join(overlapping_ipv4s)}"
    return offline_last_seen_evidence(atera, bd)


def same_company(atera: EndpointRecord, bd: EndpointRecord) -> bool:
    return normalize_key(atera.company) == normalize_key(bd.company)


def append_company_mismatch_evidence(evidence: str, atera: EndpointRecord, bd: EndpointRecord) -> str:
    if same_company(atera, bd):
        return evidence
    return f"{evidence}; Company mismatch: Atera '{atera.company}' vs BD '{bd.company}'"


def mac_overlap_evidence(atera: EndpointRecord, bd: EndpointRecord) -> str:
    overlapping_macs = sorted(set(atera.mac_addresses) & set(bd.mac_addresses))
    if not overlapping_macs:
        return ""
    return append_company_mismatch_evidence(f"MAC overlap: {'; '.join(overlapping_macs)}", atera, bd)


def find_mac_overlap_pairs(
    atera_records: Sequence[EndpointRecord],
    bd_records: Sequence[EndpointRecord],
) -> list[PotentialCandidate]:
    pairs: list[PotentialCandidate] = []
    seen_pairs: set[tuple[EndpointRecord, EndpointRecord]] = set()
    bd_by_mac: dict[str, list[EndpointRecord]] = defaultdict(list)
    for bd in bd_records:
        for mac in bd.mac_addresses:
            bd_by_mac[mac].append(bd)

    for atera in atera_records:
        for mac in atera.mac_addresses:
            for bd in bd_by_mac.get(mac, []):
                pair = (atera, bd)
                if pair in seen_pairs:
                    continue
                evidence = mac_overlap_evidence(atera, bd)
                if not evidence:
                    continue
                pairs.append(
                    PotentialCandidate(
                        atera=atera,
                        bd=bd,
                        similarity=name_similarity(atera, bd),
                        evidence=evidence,
                    )
                )
                seen_pairs.add(pair)
    return pairs


def build_mac_direct_match_rows(
    pairs: Sequence[PotentialCandidate],
    excluded_software_by_company: Mapping[str, set[str]],
) -> tuple[list[dict[str, str]], set[EndpointRecord], set[EndpointRecord]]:
    rows: list[dict[str, str]] = []
    handled_atera: set[EndpointRecord] = set()
    handled_bd: set[EndpointRecord] = set()
    pairs_by_atera: dict[EndpointRecord, list[PotentialCandidate]] = defaultdict(list)
    for pair in pairs:
        pairs_by_atera[pair.atera].append(pair)

    for atera, atera_pairs in pairs_by_atera.items():
        matched_bd_records = [pair.bd for pair in atera_pairs]
        best_pairs = [pair for pair in atera_pairs if not bd_missing_best(pair.bd)]
        if not best_pairs and not any_record_excludes_software(
            [atera],
            SOFTWARE_BD,
            excluded_software_by_company,
        ):
            evidence = join_unique([pair.evidence for pair in atera_pairs])
            similarity = max(pair.similarity for pair in atera_pairs)
            rows.append(
                build_report_row(
                    issue_type="Missing BD",
                    atera_records=[atera],
                    bd_records=matched_bd_records,
                    missing_software="Bitdefender Endpoint Protection",
                    match_evidence=f"{evidence}; BD endpoint is not managed with BEST",
                    name_similarity=format_similarity(similarity),
                )
            )

        handled_atera.add(atera)
        handled_bd.update(matched_bd_records)

    return rows, handled_atera, handled_bd


def find_potential_candidates(
    atera_records: Sequence[EndpointRecord],
    bd_records: Sequence[EndpointRecord],
) -> list[PotentialCandidate]:
    candidates: list[PotentialCandidate] = []
    seen_pairs: set[tuple[EndpointRecord, EndpointRecord]] = set()
    bd_by_company: dict[str, list[EndpointRecord]] = defaultdict(list)
    for bd in bd_records:
        bd_by_company[normalize_key(bd.company)].append(bd)

    for atera in atera_records:
        for bd in bd_by_company.get(normalize_key(atera.company), []):
            pair = (atera, bd)
            if pair in seen_pairs:
                continue
            similarity = name_similarity(atera, bd)
            evidence = potential_match_evidence(atera, bd)
            if not evidence:
                continue
            if not evidence.startswith("MAC overlap:") and similarity < NAME_SIMILARITY_THRESHOLD:
                continue
            candidates.append(PotentialCandidate(atera=atera, bd=bd, similarity=similarity, evidence=evidence))
            seen_pairs.add(pair)
    return candidates


def format_similarity(value: float) -> str:
    return f"{value * 100:.0f}%"


def build_candidate_rows(
    candidates: Sequence[PotentialCandidate],
    excluded_software_by_company: Mapping[str, set[str]],
) -> tuple[list[dict[str, str]], set[EndpointRecord], set[EndpointRecord]]:
    rows: list[dict[str, str]] = []
    handled_atera: set[EndpointRecord] = set()
    handled_bd: set[EndpointRecord] = set()
    atera_counts = Counter(candidate.atera for candidate in candidates)
    bd_counts = Counter(candidate.bd for candidate in candidates)

    for candidate in candidates:
        if bd_missing_best(candidate.bd):
            if not any_record_excludes_software(
                [candidate.atera],
                SOFTWARE_BD,
                excluded_software_by_company,
            ):
                rows.append(
                    build_report_row(
                        issue_type="Missing BD",
                        atera_records=[candidate.atera],
                        bd_records=[candidate.bd],
                        missing_software="Bitdefender Endpoint Protection",
                        match_evidence=f"{candidate.evidence}; BD endpoint is not managed with BEST",
                        name_similarity=format_similarity(candidate.similarity),
                    )
                )
            handled_atera.add(candidate.atera)
            handled_bd.add(candidate.bd)
            continue

        ambiguous = atera_counts[candidate.atera] > 1 or bd_counts[candidate.bd] > 1
        rows.append(
            build_report_row(
                issue_type="Ambiguous Potential Match Manual Review"
                if ambiguous
                else "Potential Match Manual Review",
                atera_records=[candidate.atera],
                bd_records=[candidate.bd],
                match_evidence=candidate.evidence,
                name_similarity=format_similarity(candidate.similarity),
            )
        )
        handled_atera.add(candidate.atera)
        handled_bd.add(candidate.bd)

    return rows, handled_atera, handled_bd


def compare_normalized_outputs(
    atera_rows: Sequence[tuple[Mapping[str, object], int]],
    bd_rows: Sequence[tuple[Mapping[str, object], int]],
    *,
    company_aliases: Mapping[str, str] | None = None,
    device_aliases: Mapping[tuple[str, str], str] | None = None,
    excluded_software_by_company: Mapping[str, set[str]] | None = None,
    initial_data_quality_rows: Sequence[dict[str, str]] = (),
) -> CompareOutputs:
    company_aliases = company_aliases or {}
    device_aliases = device_aliases or {}
    excluded_software_by_company = excluded_software_by_company or {}
    report_rows: list[dict[str, str]] = list(initial_data_quality_rows)
    duplicate_rows: list[dict[str, str]] = []

    atera_records, atera_data_quality_rows = build_records("atera", atera_rows, company_aliases, device_aliases)
    bd_records, bd_data_quality_rows = build_records("bd", bd_rows, company_aliases, device_aliases)
    report_rows.extend(atera_data_quality_rows)
    report_rows.extend(bd_data_quality_rows)
    duplicate_rows.extend(find_duplicate_detail_rows(atera_records, bd_records))

    mac_pairs = find_mac_overlap_pairs(atera_records, bd_records)
    mac_rows, mac_atera, mac_bd = build_mac_direct_match_rows(mac_pairs, excluded_software_by_company)
    report_rows.extend(mac_rows)
    handled_atera: set[EndpointRecord] = set(mac_atera)
    handled_bd: set[EndpointRecord] = set(mac_bd)

    remaining_atera = [record for record in atera_records if record not in handled_atera]
    remaining_bd = [record for record in bd_records if record not in handled_bd]
    primary_rows, primary_atera, primary_bd = classify_primary_matches(
        remaining_atera,
        remaining_bd,
        excluded_software_by_company,
    )
    report_rows.extend(primary_rows)
    handled_atera.update(primary_atera)
    handled_bd.update(primary_bd)

    unmatched_atera = [record for record in atera_records if record not in handled_atera]
    unmatched_bd = [record for record in bd_records if record not in handled_bd]
    candidates = find_potential_candidates(unmatched_atera, unmatched_bd)
    candidate_rows, candidate_atera, candidate_bd = build_candidate_rows(candidates, excluded_software_by_company)
    report_rows.extend(candidate_rows)

    handled_atera.update(candidate_atera)
    handled_bd.update(candidate_bd)

    for record in atera_records:
        if record in handled_atera:
            continue
        if company_excludes_software(record.company, SOFTWARE_BD, excluded_software_by_company):
            continue
        report_rows.append(
            build_report_row(
                issue_type="Missing BD",
                atera_records=[record],
                missing_software="Bitdefender Endpoint Protection",
            )
        )

    for record in bd_records:
        if record in handled_bd:
            continue
        if bd_missing_best(record):
            continue
        if company_excludes_software(record.company, SOFTWARE_ATERA, excluded_software_by_company):
            continue
        report_rows.append(
            build_report_row(
                issue_type="Missing Atera",
                bd_records=[record],
                missing_software="Atera Agent",
            )
        )

    return CompareOutputs(exception_rows=report_rows, duplicate_rows=duplicate_rows)


def compare_normalized_rows(
    atera_rows: Sequence[tuple[Mapping[str, object], int]],
    bd_rows: Sequence[tuple[Mapping[str, object], int]],
    *,
    company_aliases: Mapping[str, str] | None = None,
    device_aliases: Mapping[tuple[str, str], str] | None = None,
    excluded_software_by_company: Mapping[str, set[str]] | None = None,
    initial_data_quality_rows: Sequence[dict[str, str]] = (),
) -> list[dict[str, str]]:
    return compare_normalized_outputs(
        atera_rows,
        bd_rows,
        company_aliases=company_aliases,
        device_aliases=device_aliases,
        excluded_software_by_company=excluded_software_by_company,
        initial_data_quality_rows=initial_data_quality_rows,
    ).exception_rows


def compare_csvs(
    atera_csv: str | Path,
    bd_csv: str | Path,
    output: str | Path,
    *,
    duplicates_output: str | Path = DEFAULT_DUPLICATES_OUTPUT_PATH,
    company_aliases: str | Path | None = None,
    device_aliases: str | Path | None = None,
    exclude_company: str | Path | None = None,
) -> int:
    company_alias_map, company_alias_quality_rows = read_company_aliases(company_aliases)
    device_alias_map, device_alias_quality_rows = read_device_aliases(device_aliases, company_alias_map)
    exclude_company_map, exclude_company_quality_rows = read_exclude_company(exclude_company, company_alias_map)
    outputs = compare_normalized_outputs(
        read_csv_rows(atera_csv, ATERA_CSV_COLUMNS),
        read_csv_rows(bd_csv, BD_COMPARE_REQUIRED_COLUMNS),
        company_aliases=company_alias_map,
        device_aliases=device_alias_map,
        excluded_software_by_company=exclude_company_map,
        initial_data_quality_rows=[
            *company_alias_quality_rows,
            *device_alias_quality_rows,
            *exclude_company_quality_rows,
        ],
    )
    write_csv(output, COMPARE_REPORT_COLUMNS, outputs.exception_rows)
    write_csv(duplicates_output, DUPLICATE_REPORT_COLUMNS, outputs.duplicate_rows)
    return len(outputs.exception_rows)


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Compare normalized Atera and Bitdefender CSV data.")
    parser.add_argument(
        "--atera-csv",
        type=Path,
        default=DEFAULT_ATERA_CSV_PATH,
        help=f"Path to normalized Atera CSV. Default: {DEFAULT_ATERA_CSV_PATH}.",
    )
    parser.add_argument(
        "--bd-csv",
        type=Path,
        default=DEFAULT_BD_CSV_PATH,
        help=f"Path to normalized BD CSV. Default: {DEFAULT_BD_CSV_PATH}.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_OUTPUT_PATH,
        help=f"Path to write the mismatch report CSV. Default: {DEFAULT_OUTPUT_PATH}.",
    )
    parser.add_argument(
        "--duplicates-output",
        type=Path,
        default=DEFAULT_DUPLICATES_OUTPUT_PATH,
        help=f"Path to write duplicate entry detail CSV. Default: {DEFAULT_DUPLICATES_OUTPUT_PATH}.",
    )
    parser.add_argument(
        "--company-aliases",
        type=Path,
        default=DEFAULT_COMPANY_ALIASES_PATH,
        help=(
            "Optional company alias CSV with Atera Company Name and BD Company Name columns. "
            f"Default: {DEFAULT_COMPANY_ALIASES_PATH} if it exists."
        ),
    )
    parser.add_argument(
        "--device-aliases",
        type=Path,
        default=DEFAULT_DEVICE_ALIASES_PATH,
        help=(
            "Optional device alias CSV with Company Name, Raw Device Name, and Canonical Device Name columns. "
            f"Default: {DEFAULT_DEVICE_ALIASES_PATH} if it exists."
        ),
    )
    parser.add_argument(
        "--exclude-company",
        type=Path,
        default=DEFAULT_EXCLUDE_COMPANY_PATH,
        help=(
            "Optional company exclusion CSV with Company Name and ExcludeSoftware columns. "
            f"Default: {DEFAULT_EXCLUDE_COMPANY_PATH} if it exists."
        ),
    )
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        count = compare_csvs(
            atera_csv=args.atera_csv,
            bd_csv=args.bd_csv,
            output=args.output,
            duplicates_output=args.duplicates_output,
            company_aliases=args.company_aliases,
            device_aliases=args.device_aliases,
            exclude_company=args.exclude_company,
        )
        print(f"Wrote {count} mismatch row(s) to {args.output}")
        print(f"Wrote duplicate entry details to {args.duplicates_output}")
        return 0
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
