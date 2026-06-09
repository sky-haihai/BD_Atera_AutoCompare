from __future__ import annotations

from typing import Any


def stringify(value: Any) -> str:
    """Convert scalar input into the display string used in normalized CSV rows."""
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)


def clean_display(value: Any) -> str:
    """Trim display values without changing the meaningful body of the text."""
    return stringify(value).strip()
