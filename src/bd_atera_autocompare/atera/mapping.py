from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from ..normalization import clean_display
from .schema import AteraNormalizedRow


def join_display_values(value: Any) -> str:
    """Join list-like API values into a stable display string for CSV output."""
    if not isinstance(value, (list, tuple, set)):
        return clean_display(value)

    seen: set[str] = set()
    output: list[str] = []
    for item in value:
        text = clean_display(item)
        if not text:
            continue
        key = text.casefold()
        if key in seen:
            continue
        seen.add(key)
        output.append(text)
    return "; ".join(output)


def first_nonblank_field(raw_agent: Mapping[str, Any], field_names: tuple[str, ...]) -> str:
    """Return the first nonblank mapped value from possible Atera field names."""
    for field_name in field_names:
        value = join_display_values(raw_agent.get(field_name))
        if value:
            return value
    return ""


def convert_online_status(value: Any) -> str:
    """Map Atera Online values into comparison-friendly status text."""
    if isinstance(value, bool):
        return "Online" if value else "Offline"
    if isinstance(value, (int, float)):
        if value == 1:
            return "Online"
        if value == 0:
            return "Offline"

    text = clean_display(value)
    status_key = text.casefold()
    if status_key in {"true", "1", "yes", "online"}:
        return "Online"
    if status_key in {"false", "0", "no", "offline"}:
        return "Offline"
    return text


def map_raw_agent(raw_agent: Mapping[str, Any]) -> AteraNormalizedRow:
    """Convert one raw Atera API agent object into the normalized row contract."""
    return AteraNormalizedRow(
        device_name=clean_display(raw_agent.get("MachineName")),
        company_name=clean_display(raw_agent.get("CustomerName")),
        ip_address=first_nonblank_field(raw_agent, ("IpAddresses", "IPAddress")),
        reported_from_ip=clean_display(raw_agent.get("ReportedFromIP")),
        mac_addresses=join_display_values(raw_agent.get("MacAddresses")),
        serial_number=clean_display(raw_agent.get("VendorSerialNumber")),
        status=convert_online_status(raw_agent.get("Online")),
        last_seen=clean_display(raw_agent.get("LastSeen")),
        atera_agent_id=clean_display(raw_agent.get("AgentID")),
        atera_machine_id=clean_display(raw_agent.get("MachineID")),
        atera_device_guid=first_nonblank_field(raw_agent, ("DeviceGuid", "DeviceGUID")),
    )

