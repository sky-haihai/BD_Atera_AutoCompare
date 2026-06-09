from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime
from typing import Any

from ..normalization import clean_display
from .schema import BdNormalizedRow


BD_REPORT_REQUIRED_HEADERS = [
    "Endpoint Name",
    "Company Name",
    "IP",
    "Update Status",
    "Last Update",
    "Online",
]

BD_REPORT_TIMESTAMP_FORMATS = (
    "%d %B %Y, %H:%M:%S",
    "%d %b %Y, %H:%M:%S",
)


def is_bd_report_timestamp(value: Any) -> bool:
    """Return whether a BD report value looks like the report's local timestamp format."""
    text = clean_display(value)
    if not text:
        return False

    for timestamp_format in BD_REPORT_TIMESTAMP_FORMATS:
        try:
            datetime.strptime(text, timestamp_format)
            return True
        except ValueError:
            continue
    return False


def convert_bd_online_status(online_value: Any, update_status: Any = "") -> str:
    """Map the BD report Online column into comparison-friendly status text."""
    online_text = clean_display(online_value)
    if not online_text:
        return clean_display(update_status)

    status_key = online_text.casefold()
    if status_key == "online":
        return "Online"
    if status_key == "unmanaged":
        return "Unmanaged"
    if status_key in {"offline", "inactive", "disconnected"}:
        return "Offline"
    if is_bd_report_timestamp(online_text):
        return "Offline"
    return online_text


def map_bd_last_seen(source_row: Mapping[str, Any]) -> str:
    """Extract Last Seen from the BD report, where offline rows store it in Online."""
    online_text = clean_display(source_row.get("Online"))
    if is_bd_report_timestamp(online_text):
        return online_text

    if not online_text:
        return clean_display(source_row.get("Last Update"))

    return ""


def map_bd_report_row(source_row: Mapping[str, Any], row_number: int) -> BdNormalizedRow:
    """Convert one manual BD report row into the normalized row contract."""
    return BdNormalizedRow(
        device_name=clean_display(source_row.get("Endpoint Name")),
        company_name=clean_display(source_row.get("Company Name")),
        ip_address=clean_display(source_row.get("IP")),
        status=convert_bd_online_status(source_row.get("Online"), source_row.get("Update Status")),
        last_seen=map_bd_last_seen(source_row),
        bd_row_number=clean_display(row_number),
    )

