from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from .atera_schema import AteraNormalizedRow
from .normalization import clean_display


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
        ip_address=clean_display(raw_agent.get("IPAddress")),
        status=convert_online_status(raw_agent.get("Online")),
        last_seen=clean_display(raw_agent.get("LastSeen")),
        atera_agent_id=clean_display(raw_agent.get("AgentID")),
        atera_machine_id=clean_display(raw_agent.get("MachineID")),
        atera_device_guid=clean_display(raw_agent.get("DeviceGUID")),
    )
