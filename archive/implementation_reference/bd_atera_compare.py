#!/usr/bin/env python3
"""Compare Atera agents with a manual Bitdefender Endpoint Protection CSV."""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import difflib
import ipaddress
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

try:
    from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
except ImportError:  # pragma: no cover - Python 3.9+ has zoneinfo.
    ZoneInfo = None

    class ZoneInfoNotFoundError(Exception):
        pass


BD_REQUIRED_HEADERS = ["Device Name", "Company Name", "IP Address", "Status", "Last Seen"]
ALIAS_REQUIRED_HEADERS = ["Company Name", "Raw Device Name", "Canonical Device Name"]

ATERA_DEVICE_FIELD = "MachineName"
ATERA_COMPANY_FIELD = "CustomerName"
ATERA_IP_FIELD = "IPAddress"
ATERA_STATUS_FIELD = "Online"
ATERA_LAST_SEEN_FIELD = "LastSeen"

OUTPUT_COLUMNS = [
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
    "Alias Applied",
    "Notes",
]

NAME_SIMILARITY_THRESHOLD = 0.80
LAST_SEEN_WINDOW_MINUTES = 60
DEFAULT_ATERA_BASE_URL = "https://app.atera.com/api/v3"
DEFAULT_PAGE_SIZE = 100
MAX_ATERA_PAGES = 1000

IPV4_RE = re.compile(r"(?<![\d.])(?:\d{1,3}\.){3}\d{1,3}(?![\d.])")
LOCAL_TZ_NAME = "America/Edmonton"


def _local_timezone() -> dt.tzinfo:
    if ZoneInfo is not None:
        try:
            return ZoneInfo(LOCAL_TZ_NAME)
        except ZoneInfoNotFoundError:
            pass
    return dt.timezone(dt.timedelta(hours=-6), LOCAL_TZ_NAME)


LOCAL_TZ = _local_timezone()


@dataclass
class EndpointRecord:
    source: str
    raw_device: str
    canonical_device: str
    company: str
    ip_raw: str = ""
    ipv4s: set[str] = field(default_factory=set)
    status_raw: str = ""
    offline: bool = False
    last_seen_raw: str = ""
    last_seen: dt.datetime | None = None
    last_seen_has_time: bool = False
    row_number: str = ""
    agent_id: str = ""
    machine_id: str = ""
    device_guid: str = ""
    alias_applied: bool = False
    notes: list[str] = field(default_factory=list)

    @property
    def company_key(self) -> str:
        return normalize_key(self.company)

    @property
    def device_key(self) -> str:
        return normalize_key(self.canonical_device)

    @property
    def match_key(self) -> tuple[str, str]:
        return (self.company_key, self.device_key)


@dataclass
class PotentialCandidate:
    atera: EndpointRecord
    bd: EndpointRecord
    similarity: float
    evidence: str


def normalize_key(value: Any) -> str:
    return stringify(value).strip().casefold()


def stringify(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)


def clean_display(value: Any) -> str:
    return stringify(value).strip()


def blank_output_row() -> dict[str, str]:
    return {column: "" for column in OUTPUT_COLUMNS}


def unique_join(values: list[Any] | set[Any]) -> str:
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
    return "; ".join(output)


def extract_ipv4s(value: Any) -> set[str]:
    ips: set[str] = set()
    for candidate in IPV4_RE.findall(stringify(value)):
        try:
            ips.add(str(ipaddress.IPv4Address(candidate)))
        except ipaddress.AddressValueError:
            continue
    return ips


def is_offline_status(value: Any) -> bool:
    if isinstance(value, bool):
        return not value
    if isinstance(value, (int, float)):
        return value == 0

    text = clean_display(value).casefold()
    if not text:
        return False
    return text in {
        "0",
        "false",
        "no",
        "off",
        "offline",
        "disconnected",
        "inactive",
        "down",
        "not connected",
    }


def parse_last_seen(value: Any) -> tuple[dt.datetime | None, bool]:
    text = clean_display(value)
    if not text:
        return None, False

    iso_text = text
    if iso_text.endswith("Z"):
        iso_text = f"{iso_text[:-1]}+00:00"
    try:
        parsed = dt.datetime.fromisoformat(iso_text)
        return localize_datetime(parsed), parsed.time() != dt.time()
    except ValueError:
        pass

    formats_with_time = [
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%d %H:%M",
        "%Y/%m/%d %H:%M:%S",
        "%Y/%m/%d %H:%M",
        "%m/%d/%Y %I:%M:%S %p",
        "%m/%d/%Y %I:%M %p",
        "%m/%d/%Y %H:%M:%S",
        "%m/%d/%Y %H:%M",
        "%d/%m/%Y %H:%M:%S",
        "%d/%m/%Y %H:%M",
        "%b %d, %Y %I:%M:%S %p",
        "%b %d, %Y %I:%M %p",
        "%B %d, %Y %I:%M:%S %p",
        "%B %d, %Y %I:%M %p",
    ]
    date_only_formats = ["%Y-%m-%d", "%Y/%m/%d", "%m/%d/%Y", "%d/%m/%Y"]

    for fmt in formats_with_time:
        try:
            return localize_datetime(dt.datetime.strptime(text, fmt)), True
        except ValueError:
            continue

    for fmt in date_only_formats:
        try:
            return localize_datetime(dt.datetime.strptime(text, fmt)), False
        except ValueError:
            continue

    return None, False


def localize_datetime(value: dt.datetime) -> dt.datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=LOCAL_TZ)
    return value.astimezone(LOCAL_TZ)


def last_seen_close(left: EndpointRecord, right: EndpointRecord) -> tuple[bool, str]:
    if not left.last_seen or not right.last_seen:
        return False, ""
    if not left.last_seen_has_time or not right.last_seen_has_time:
        return False, ""

    left_local = left.last_seen.astimezone(LOCAL_TZ)
    right_local = right.last_seen.astimezone(LOCAL_TZ)
    if left_local.date() != right_local.date():
        return False, ""

    delta_minutes = abs((left_local - right_local).total_seconds()) / 60
    if delta_minutes <= LAST_SEEN_WINDOW_MINUTES:
        return True, f"offline last seen within {delta_minutes:.0f} minutes"
    return False, ""


def name_similarity(left: str, right: str) -> float:
    return difflib.SequenceMatcher(None, normalize_key(left), normalize_key(right)).ratio()


def require_headers(fieldnames: list[str] | None, required: list[str], path: Path) -> None:
    actual = set(fieldnames or [])
    missing = [header for header in required if header not in actual]
    if missing:
        raise ValueError(f"{path} is missing required header(s): {', '.join(missing)}")


def read_csv_dicts(path: Path, required_headers: list[str]) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        require_headers(reader.fieldnames, required_headers, path)
        rows: list[dict[str, str]] = []
        for row_number, row in enumerate(reader, start=2):
            row = dict(row)
            row["_csv_row_number"] = str(row_number)
            rows.append(row)
        return rows


def load_device_aliases(path: Path | None) -> tuple[dict[tuple[str, str], str], list[dict[str, str]]]:
    if path is None:
        return {}, []

    rows = read_csv_dicts(path, ALIAS_REQUIRED_HEADERS)
    aliases: dict[tuple[str, str], str] = {}
    data_quality_rows: list[dict[str, str]] = []

    for row in rows:
        company = clean_display(row.get("Company Name"))
        raw_device = clean_display(row.get("Raw Device Name"))
        canonical_device = clean_display(row.get("Canonical Device Name"))
        row_number = row.get("_csv_row_number", "")
        missing = [
            header
            for header, value in [
                ("Company Name", company),
                ("Raw Device Name", raw_device),
                ("Canonical Device Name", canonical_device),
            ]
            if not value
        ]
        if missing:
            data_quality_rows.append(
                data_quality_row(
                    issue=f"Alias row {row_number} missing required value(s): {', '.join(missing)}",
                    notes="Alias row ignored.",
                )
            )
            continue
        aliases[(normalize_key(company), normalize_key(raw_device))] = canonical_device

    return aliases, data_quality_rows


def apply_alias(
    aliases: dict[tuple[str, str], str],
    company: str,
    device: str,
) -> tuple[str, bool]:
    canonical = aliases.get((normalize_key(company), normalize_key(device)))
    if canonical:
        return canonical, True
    return clean_display(device), False


def build_atera_records(
    agents: list[dict[str, Any]],
    aliases: dict[tuple[str, str], str],
) -> tuple[list[EndpointRecord], list[dict[str, str]]]:
    records: list[EndpointRecord] = []
    data_quality_rows: list[dict[str, str]] = []

    for index, agent in enumerate(agents, start=1):
        device = clean_display(agent.get(ATERA_DEVICE_FIELD))
        company = clean_display(agent.get(ATERA_COMPANY_FIELD))
        missing = []
        if not device:
            missing.append(ATERA_DEVICE_FIELD)
        if not company:
            missing.append(ATERA_COMPANY_FIELD)
        if missing:
            data_quality_rows.append(
                data_quality_row(
                    atera_device=device,
                    company=company,
                    issue=f"Atera item {index} missing required field(s): {', '.join(missing)}",
                )
            )
            continue

        canonical, alias_applied = apply_alias(aliases, company, device)
        ip_raw = clean_display(agent.get(ATERA_IP_FIELD))
        status_raw = stringify(agent.get(ATERA_STATUS_FIELD))
        last_seen_raw = clean_display(agent.get(ATERA_LAST_SEEN_FIELD))
        last_seen, last_seen_has_time = parse_last_seen(last_seen_raw)

        records.append(
            EndpointRecord(
                source="Atera",
                raw_device=device,
                canonical_device=canonical,
                company=company,
                ip_raw=ip_raw,
                ipv4s=extract_ipv4s(ip_raw),
                status_raw=status_raw,
                offline=is_offline_status(agent.get(ATERA_STATUS_FIELD)),
                last_seen_raw=last_seen_raw,
                last_seen=last_seen,
                last_seen_has_time=last_seen_has_time,
                agent_id=clean_display(agent.get("AgentID")),
                machine_id=clean_display(agent.get("MachineID")),
                device_guid=clean_display(agent.get("DeviceGUID")),
                alias_applied=alias_applied,
            )
        )

    return records, data_quality_rows


def build_bd_records(
    rows: list[dict[str, str]],
    aliases: dict[tuple[str, str], str],
) -> tuple[list[EndpointRecord], list[dict[str, str]]]:
    records: list[EndpointRecord] = []
    data_quality_rows: list[dict[str, str]] = []

    for row in rows:
        device = clean_display(row.get("Device Name"))
        company = clean_display(row.get("Company Name"))
        row_number = row.get("_csv_row_number", "")
        missing = []
        if not device:
            missing.append("Device Name")
        if not company:
            missing.append("Company Name")
        if missing:
            data_quality_rows.append(
                data_quality_row(
                    bd_device=device,
                    company=company,
                    issue=f"BD row {row_number} missing required value(s): {', '.join(missing)}",
                    bd_row_numbers=row_number,
                )
            )
            continue

        canonical, alias_applied = apply_alias(aliases, company, device)
        ip_raw = clean_display(row.get("IP Address"))
        last_seen_raw = clean_display(row.get("Last Seen"))
        last_seen, last_seen_has_time = parse_last_seen(last_seen_raw)

        records.append(
            EndpointRecord(
                source="BD",
                raw_device=device,
                canonical_device=canonical,
                company=company,
                ip_raw=ip_raw,
                ipv4s=extract_ipv4s(ip_raw),
                status_raw=clean_display(row.get("Status")),
                offline=is_offline_status(row.get("Status")),
                last_seen_raw=last_seen_raw,
                last_seen=last_seen,
                last_seen_has_time=last_seen_has_time,
                row_number=row_number,
                alias_applied=alias_applied,
            )
        )

    return records, data_quality_rows


def data_quality_row(
    issue: str,
    notes: str = "",
    atera_device: str = "",
    bd_device: str = "",
    company: str = "",
    bd_row_numbers: str = "",
) -> dict[str, str]:
    row = blank_output_row()
    row["Atera Device Name"] = atera_device
    row["BD Device Name"] = bd_device
    row["Company Name"] = company
    row["Issue Type"] = "Data Quality Review"
    row["BD Row Numbers"] = bd_row_numbers
    row["Notes"] = "; ".join(part for part in [issue, notes] if part)
    return row


def records_by_key(records: list[EndpointRecord]) -> dict[tuple[str, str], list[EndpointRecord]]:
    grouped: dict[tuple[str, str], list[EndpointRecord]] = defaultdict(list)
    for record in records:
        grouped[record.match_key].append(record)
    return grouped


def compare_records(
    atera_records: list[EndpointRecord],
    bd_records: list[EndpointRecord],
    data_quality_rows: list[dict[str, str]] | None = None,
) -> list[dict[str, str]]:
    output: list[dict[str, str]] = list(data_quality_rows or [])
    atera_by_key = records_by_key(atera_records)
    bd_by_key = records_by_key(bd_records)
    all_keys = sorted(set(atera_by_key) | set(bd_by_key))

    consumed_atera: set[int] = set()
    consumed_bd: set[int] = set()
    unmatched_atera: list[EndpointRecord] = []
    unmatched_bd: list[EndpointRecord] = []

    for key in all_keys:
        atera_group = atera_by_key.get(key, [])
        bd_group = bd_by_key.get(key, [])

        if len(atera_group) > 1 or len(bd_group) > 1:
            output.append(
                output_row_for_groups(
                    atera_group,
                    bd_group,
                    issue_type="Duplicate Manual Review",
                    notes="Duplicate company plus canonical device found after aliasing.",
                )
            )
            consumed_atera.update(id(record) for record in atera_group)
            consumed_bd.update(id(record) for record in bd_group)
            continue

        if len(atera_group) == 1 and len(bd_group) == 1:
            consumed_atera.add(id(atera_group[0]))
            consumed_bd.add(id(bd_group[0]))
            continue

        if len(atera_group) == 1:
            unmatched_atera.append(atera_group[0])
            continue

        if len(bd_group) == 1:
            unmatched_bd.append(bd_group[0])

    candidates = find_potential_candidates(unmatched_atera, unmatched_bd)
    apply_potential_candidates(candidates, output, consumed_atera, consumed_bd)

    for record in unmatched_atera:
        if id(record) in consumed_atera:
            continue
        output.append(
            output_row_for_groups(
                [record],
                [],
                issue_type="Missing BD",
                missing_software="Bitdefender Endpoint Protection",
            )
        )

    for record in unmatched_bd:
        if id(record) in consumed_bd:
            continue
        output.append(
            output_row_for_groups(
                [],
                [record],
                issue_type="Missing Atera",
                missing_software="Atera Agent",
            )
        )

    return output


def find_potential_candidates(
    unmatched_atera: list[EndpointRecord],
    unmatched_bd: list[EndpointRecord],
) -> list[PotentialCandidate]:
    candidates: list[PotentialCandidate] = []
    bd_by_company: dict[str, list[EndpointRecord]] = defaultdict(list)
    for bd_record in unmatched_bd:
        bd_by_company[bd_record.company_key].append(bd_record)

    for atera_record in unmatched_atera:
        for bd_record in bd_by_company.get(atera_record.company_key, []):
            similarity = name_similarity(atera_record.canonical_device, bd_record.canonical_device)
            if similarity < NAME_SIMILARITY_THRESHOLD:
                continue

            overlap = sorted(atera_record.ipv4s & bd_record.ipv4s)
            if overlap:
                candidates.append(
                    PotentialCandidate(
                        atera=atera_record,
                        bd=bd_record,
                        similarity=similarity,
                        evidence=f"IPv4 match: {', '.join(overlap)}",
                    )
                )
                continue

            if atera_record.offline and bd_record.offline:
                close, evidence = last_seen_close(atera_record, bd_record)
                if close:
                    candidates.append(
                        PotentialCandidate(
                            atera=atera_record,
                            bd=bd_record,
                            similarity=similarity,
                            evidence=evidence,
                        )
                    )

    return candidates


def apply_potential_candidates(
    candidates: list[PotentialCandidate],
    output: list[dict[str, str]],
    consumed_atera: set[int],
    consumed_bd: set[int],
) -> None:
    if not candidates:
        return

    atera_counts = Counter(id(candidate.atera) for candidate in candidates)
    bd_counts = Counter(id(candidate.bd) for candidate in candidates)

    ambiguous_candidates = [
        candidate
        for candidate in candidates
        if atera_counts[id(candidate.atera)] > 1 or bd_counts[id(candidate.bd)] > 1
    ]
    ambiguous_atera = {id(candidate.atera) for candidate in ambiguous_candidates}
    ambiguous_bd = {id(candidate.bd) for candidate in ambiguous_candidates}

    for candidate in ambiguous_candidates:
        output.append(
            output_row_for_candidate(
                candidate,
                issue_type="Ambiguous Potential Match Manual Review",
                notes="Multiple possible low-confidence counterparts found; verify manually.",
            )
        )
        consumed_atera.add(id(candidate.atera))
        consumed_bd.add(id(candidate.bd))

    for candidate in candidates:
        if id(candidate.atera) in ambiguous_atera or id(candidate.bd) in ambiguous_bd:
            continue
        output.append(
            output_row_for_candidate(
                candidate,
                issue_type="Potential Match Manual Review",
                notes="Low-confidence pair; verify manually.",
            )
        )
        consumed_atera.add(id(candidate.atera))
        consumed_bd.add(id(candidate.bd))


def output_row_for_candidate(
    candidate: PotentialCandidate,
    issue_type: str,
    notes: str,
) -> dict[str, str]:
    row = output_row_for_groups(
        [candidate.atera],
        [candidate.bd],
        issue_type=issue_type,
        notes=notes,
    )
    row["Match Evidence"] = candidate.evidence
    row["Name Similarity"] = f"{candidate.similarity:.0%}"
    return row


def output_row_for_groups(
    atera_records: list[EndpointRecord],
    bd_records: list[EndpointRecord],
    issue_type: str,
    missing_software: str = "",
    notes: str = "",
) -> dict[str, str]:
    row = blank_output_row()
    all_records = atera_records + bd_records

    row["Atera Device Name"] = unique_join([record.raw_device for record in atera_records])
    row["BD Device Name"] = unique_join([record.raw_device for record in bd_records])
    row["Canonical Device Name"] = unique_join([record.canonical_device for record in all_records])
    row["Company Name"] = unique_join([record.company for record in all_records])
    row["Missing Software"] = missing_software
    row["Issue Type"] = issue_type
    row["Atera IPv4"] = unique_join(sorted(ip for record in atera_records for ip in record.ipv4s))
    row["BD IPv4"] = unique_join(sorted(ip for record in bd_records for ip in record.ipv4s))
    row["Atera Status"] = unique_join([record.status_raw for record in atera_records])
    row["BD Status"] = unique_join([record.status_raw for record in bd_records])
    row["Atera Last Seen"] = unique_join([record.last_seen_raw for record in atera_records])
    row["BD Last Seen"] = unique_join([record.last_seen_raw for record in bd_records])
    row["Atera Count"] = str(len(atera_records))
    row["BD Count"] = str(len(bd_records))
    row["Atera Agent IDs"] = unique_join([record.agent_id for record in atera_records])
    row["Atera Machine IDs"] = unique_join([record.machine_id for record in atera_records])
    row["Atera Device GUIDs"] = unique_join([record.device_guid for record in atera_records])
    row["BD Row Numbers"] = unique_join([record.row_number for record in bd_records])
    row["Alias Applied"] = "Yes" if any(record.alias_applied for record in all_records) else "No"
    row["Notes"] = unique_join([notes] + [note for record in all_records for note in record.notes])
    return row


def compare_agent_payload_to_bd_csv(
    atera_agents: list[dict[str, Any]],
    bd_report_path: Path,
    alias_path: Path | None = None,
) -> list[dict[str, str]]:
    aliases, alias_quality_rows = load_device_aliases(alias_path)
    bd_rows = read_csv_dicts(bd_report_path, BD_REQUIRED_HEADERS)
    atera_records, atera_quality_rows = build_atera_records(atera_agents, aliases)
    bd_records, bd_quality_rows = build_bd_records(bd_rows, aliases)
    return compare_records(
        atera_records,
        bd_records,
        alias_quality_rows + atera_quality_rows + bd_quality_rows,
    )


def write_output_csv(path: Path, rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=OUTPUT_COLUMNS)
        writer.writeheader()
        writer.writerows(rows)


def fetch_atera_agents(base_url: str, api_key: str, timeout: float = 30.0) -> list[dict[str, Any]]:
    if not api_key:
        raise ValueError("ATERA_API_KEY is required.")

    normalized_base = base_url.rstrip("/")
    all_agents: list[dict[str, Any]] = []
    seen_page_signatures: set[str] = set()

    for page in range(1, MAX_ATERA_PAGES + 1):
        query = urllib.parse.urlencode({"page": page, "itemsInPage": DEFAULT_PAGE_SIZE})
        url = f"{normalized_base}/agents?{query}"
        payload = request_json(url, api_key, timeout)
        page_agents = extract_agent_items(payload)

        signature = json.dumps(page_agents[:3], sort_keys=True, default=str)
        if page > 1 and signature in seen_page_signatures:
            break
        seen_page_signatures.add(signature)

        if not page_agents:
            break
        all_agents.extend(page_agents)

        total_pages = extract_int(payload, ["totalPages", "TotalPages", "total_pages"])
        if total_pages is not None and page >= total_pages:
            break

        total_count = extract_int(payload, ["totalCount", "TotalCount", "total_count"])
        if total_count is not None and len(all_agents) >= total_count:
            break

        if len(page_agents) < DEFAULT_PAGE_SIZE:
            break

    return all_agents


def request_json(url: str, api_key: str, timeout: float) -> Any:
    headers = {"X-API-KEY": api_key, "Accept": "application/json"}
    request = urllib.request.Request(url, headers=headers, method="GET")

    last_error: Exception | None = None
    for attempt in range(3):
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                body = response.read().decode("utf-8")
                return json.loads(body)
        except urllib.error.HTTPError as exc:
            if exc.code not in {429, 500, 502, 503, 504}:
                detail = exc.read().decode("utf-8", errors="replace")
                raise RuntimeError(f"Atera API request failed with HTTP {exc.code}: {detail}") from exc
            last_error = exc
        except urllib.error.URLError as exc:
            last_error = exc

        if attempt < 2:
            time.sleep(2**attempt)

    raise RuntimeError(f"Atera API request failed after retries: {last_error}") from last_error


def extract_agent_items(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]

    if not isinstance(payload, dict):
        raise ValueError("Atera API response must be a JSON object or array.")

    for key in ["items", "Items", "data", "Data", "agents", "Agents", "value", "Value"]:
        value = payload.get(key)
        if isinstance(value, list):
            return [item for item in value if isinstance(item, dict)]

    list_values = [value for value in payload.values() if isinstance(value, list)]
    dict_lists = [
        value
        for value in list_values
        if all(isinstance(item, dict) for item in value)
    ]
    if len(dict_lists) == 1:
        return dict_lists[0]

    raise ValueError("Could not find the agents list in the Atera API response.")


def extract_int(payload: Any, keys: list[str]) -> int | None:
    if not isinstance(payload, dict):
        return None
    for key in keys:
        value = payload.get(key)
        if value is None:
            continue
        try:
            return int(value)
        except (TypeError, ValueError):
            continue
    return None


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Compare Atera agents with a manual Bitdefender Endpoint Protection Status CSV.",
    )
    parser.add_argument("--bd-report", required=True, type=Path, help="Path to the manual BD report CSV.")
    parser.add_argument("--output", required=True, type=Path, help="Path to write the exception CSV.")
    parser.add_argument(
        "--device-aliases",
        type=Path,
        default=None,
        help="Optional CSV with Company Name, Raw Device Name, Canonical Device Name.",
    )
    parser.add_argument(
        "--http-timeout",
        type=float,
        default=30.0,
        help="Atera API HTTP timeout in seconds. Default: 30.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        api_key = os.environ.get("ATERA_API_KEY", "")
        base_url = os.environ.get("ATERA_BASE_URL", DEFAULT_ATERA_BASE_URL)
        atera_agents = fetch_atera_agents(base_url, api_key, timeout=args.http_timeout)
        rows = compare_agent_payload_to_bd_csv(atera_agents, args.bd_report, args.device_aliases)
        write_output_csv(args.output, rows)
        print(f"Wrote {len(rows)} exception row(s) to {args.output}")
        return 0
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
