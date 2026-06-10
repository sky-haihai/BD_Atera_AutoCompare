from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from ..normalization import clean_display
from .schema import BdNormalizedRow


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


def bool_display(value: Any) -> str:
    """Return a stable display string for API boolean fields."""
    if isinstance(value, bool):
        return "true" if value else "false"
    return clean_display(value)


def nested_mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def network_item_details(item: Mapping[str, Any]) -> Mapping[str, Any]:
    """Return the getNetworkInventoryItems details object when present."""
    return nested_mapping(item.get("details"))


def endpoint_status(details: Mapping[str, Any]) -> str:
    """Convert inventory endpoint security flags into a comparison-friendly status."""
    managed_with_best = details.get("managedWithBest")
    if isinstance(managed_with_best, bool):
        return "Managed With BEST" if managed_with_best else "No BEST"

    is_managed = details.get("isManaged")
    if isinstance(is_managed, bool):
        return "Managed" if is_managed else "Unmanaged"

    return ""


def endpoint_company_name(
    item: Mapping[str, Any],
    details: Mapping[str, Any],
    company_names_by_id: Mapping[str, str] | None = None,
    fallback_company_name: str = "",
) -> str:
    """Resolve endpoint company from inventory companyId, moving info, or caller fallback."""
    company_id = clean_display(item.get("companyId"))
    if company_id and company_names_by_id is not None:
        company_name = clean_display(company_names_by_id.get(company_id))
        if company_name:
            return company_name

    moving_info = details.get("movingInfo")
    if isinstance(moving_info, Mapping):
        destination = clean_display(moving_info.get("destinationCompanyName"))
        if destination:
            return destination

    return clean_display(item.get("companyName")) or clean_display(fallback_company_name)


def format_modules(modules: Any) -> str:
    """Return endpoint module states as a stable display string."""
    if not isinstance(modules, Mapping):
        return ""

    output: list[str] = []
    for key in sorted(modules):
        value = modules[key]
        if isinstance(value, bool):
            output.append(f"{key}={bool_display(value)}")
        else:
            text = clean_display(value)
            if text:
                output.append(f"{key}={text}")
    return "; ".join(output)


def map_inventory_endpoint_item(
    item: Mapping[str, Any],
    company_names_by_id: Mapping[str, str] | None = None,
    fallback_company_name: str = "",
) -> BdNormalizedRow:
    """Convert one getNetworkInventoryItems endpoint item into a normalized BD row."""
    details = network_item_details(item)
    policy = nested_mapping(details.get("policy"))
    moving_info = nested_mapping(details.get("movingInfo"))
    last_successful_scan = nested_mapping(details.get("lastSuccessfulScan"))

    return BdNormalizedRow(
        device_name=clean_display(item.get("name")),
        company_name=endpoint_company_name(item, details, company_names_by_id, fallback_company_name),
        ip_address=clean_display(details.get("ip")),
        status=endpoint_status(details),
        bd_endpoint_id=clean_display(item.get("id")),
        bd_company_id=clean_display(item.get("companyId")),
        parent_id=clean_display(item.get("parentId")),
        network_item_type=clean_display(item.get("type")),
        is_in_deleted_folder=bool_display(item.get("isInDeletedFolder")),
        label=clean_display(details.get("label")),
        fqdn=clean_display(details.get("fqdn")),
        group_id=clean_display(details.get("groupId")) or clean_display(item.get("parentId")),
        mac_addresses=join_display_values(details.get("macs")),
        ssid=clean_display(details.get("ssid")),
        is_managed=bool_display(details.get("isManaged")),
        managed_with_best=bool_display(details.get("managedWithBest")),
        machine_type=clean_display(details.get("machineType")),
        operating_system_version=clean_display(details.get("operatingSystemVersion")),
        is_container_host=bool_display(details.get("isContainerHost")),
        managed_exchange_server=bool_display(details.get("managedExchangeServer")),
        managed_relay=bool_display(details.get("managedRelay")),
        security_server=bool_display(details.get("securityServer")),
        policy_id=clean_display(policy.get("id")),
        policy_name=clean_display(policy.get("name")),
        policy_applied=bool_display(policy.get("applied")),
        moving_state=clean_display(moving_info.get("state")),
        destination_company_name=clean_display(moving_info.get("destinationCompanyName")),
        product_outdated=bool_display(details.get("productOutdated")),
        last_successful_scan_name=clean_display(last_successful_scan.get("name")),
        last_successful_scan_date=clean_display(last_successful_scan.get("date")),
        modules=format_modules(details.get("modules")),
    )

map_endpoint_item = map_inventory_endpoint_item
