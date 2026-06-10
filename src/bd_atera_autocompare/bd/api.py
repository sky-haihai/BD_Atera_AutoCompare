from __future__ import annotations

import base64
import json
import os
import time
import urllib.error
import urllib.request
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Any
from uuid import uuid4

from ..env_file import load_env_file
from ..normalization import clean_display
from .mapping import map_inventory_endpoint_item
from .schema import BdNormalizedRow


DEFAULT_BD_API_URL = "https://cloud.gravityzone.bitdefender.com/api/v1.0/jsonrpc/network"
DEFAULT_BD_USER_AGENT = "BD-Atera-AutoCompare/0.1"
DEFAULT_PAGE_SIZE = 100
DELETED_FOLDER_PAGE_SIZE = 1000
DELETED_FOLDER_NAME = "Deleted"
MAX_BD_PAGES = 1000
TRANSIENT_HTTP_CODES = {429, 500, 502, 503, 504}
COMPANY_ITEM_TYPE = 1
ENDPOINT_ITEM_TYPES = {5, 6, 7}
COMPANY_ITEM_TYPE_KEY = str(COMPANY_ITEM_TYPE)
ENDPOINT_ITEM_TYPE_KEYS = {str(item_type) for item_type in ENDPOINT_ITEM_TYPES}


class BdApiProvider:
    def __init__(
        self,
        api_key: str,
        *,
        api_url: str = DEFAULT_BD_API_URL,
        user_agent: str = DEFAULT_BD_USER_AGENT,
        timeout: float = 30.0,
        page_size: int = DEFAULT_PAGE_SIZE,
        max_pages: int = MAX_BD_PAGES,
        parent_id: str = "",
        company_name: str = "",
        recursive: bool = True,
        return_product_outdated: bool = True,
        include_scan_logs: bool = True,
        include_unprotected: bool = False,
        urlopen: Callable[..., Any] | None = None,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        """Configure the Bitdefender getNetworkInventoryItems API provider."""
        self.api_key = clean_display(api_key)
        if not self.api_key:
            raise ValueError("BD_API_KEY is required.")

        self.api_url = clean_display(api_url) or DEFAULT_BD_API_URL
        self.user_agent = clean_display(user_agent) or DEFAULT_BD_USER_AGENT
        self.timeout = timeout
        self.page_size = page_size
        self.max_pages = max_pages
        self.parent_id = clean_display(parent_id)
        self.company_name = clean_display(company_name)
        self.recursive = recursive
        self.return_product_outdated = return_product_outdated
        self.include_scan_logs = include_scan_logs
        self.include_unprotected = include_unprotected
        self._urlopen = urlopen or urllib.request.urlopen
        self._sleep = sleep

    @classmethod
    def from_environment(
        cls,
        environ: Mapping[str, str] | None = None,
        env_file: str | Path | None = ".env",
        **kwargs: Any,
    ) -> BdApiProvider:
        """Build a provider from local .env values with process environment fallback."""
        process_env = os.environ if environ is None else environ
        file_env = load_env_file(env_file) if env_file is not None else {}
        values = {**process_env, **file_env}

        init_kwargs: dict[str, Any] = {
            "api_key": values.get("BD_API_KEY") or values.get("BITDEFENDER_API_KEY", ""),
            "api_url": values.get("BD_API_URL") or values.get("BITDEFENDER_API_URL", DEFAULT_BD_API_URL),
            "user_agent": values.get("BD_USER_AGENT")
            or values.get("BITDEFENDER_USER_AGENT", DEFAULT_BD_USER_AGENT),
            "parent_id": values.get("BD_PARENT_ID") or values.get("BITDEFENDER_PARENT_ID", ""),
            "company_name": values.get("BD_COMPANY_NAME") or values.get("BITDEFENDER_COMPANY_NAME", ""),
        }
        init_kwargs.update(kwargs)
        return cls(**init_kwargs)

    def get_rows(self) -> list[BdNormalizedRow]:
        """Fetch endpoint inventory and map it to normalized BD rows."""
        inventory_items = self.fetch_inventory_items()
        deleted_group_id = self.fetch_deleted_folder_id()
        deleted_items = self.fetch_deleted_folder_items(deleted_group_id) if deleted_group_id else []
        inventory_items = merge_inventory_items(inventory_items, deleted_items, deleted_group_id)
        company_names_by_id = build_company_names_by_id(inventory_items)
        return [
            map_inventory_endpoint_item(item, company_names_by_id, self.company_name)
            for item in filter_endpoint_items(inventory_items)
        ]

    def fetch_inventory_items(self) -> list[dict[str, Any]]:
        """Fetch all getNetworkInventoryItems pages as raw inventory dictionaries."""
        return self._fetch_inventory_pages(self._request_payload, self.page_size)

    def fetch_deleted_folder_id(self) -> str:
        """Return the custom group ID named Deleted, or blank when the folder is absent."""
        payload = self.request_json(self._custom_groups_payload())
        result = extract_jsonrpc_result(payload)
        return find_deleted_group_id(extract_custom_group_items(result))

    def fetch_deleted_folder_items(self, deleted_group_id: str) -> list[dict[str, Any]]:
        """Fetch all endpoint items under the Deleted custom group."""
        clean_deleted_group_id = clean_display(deleted_group_id)
        if not clean_deleted_group_id:
            return []

        return [
            mark_deleted_folder_item(item)
            for item in self._fetch_inventory_pages(
                lambda page: self._deleted_folder_request_payload(clean_deleted_group_id, page),
                DELETED_FOLDER_PAGE_SIZE,
            )
        ]

    def _fetch_inventory_pages(
        self,
        payload_factory: Callable[[int], Mapping[str, Any]],
        page_size: int,
    ) -> list[dict[str, Any]]:
        """Fetch all paged getNetworkInventoryItems responses for a payload shape."""
        all_items: list[dict[str, Any]] = []

        for page in range(1, self.max_pages + 1):
            payload = self.request_json(payload_factory(page))
            result = extract_result(payload)
            page_items = extract_inventory_items(result)
            all_items.extend(page_items)

            has_more = result.get("hasMoreRecords")
            pages_count = extract_int(result, "pagesCount")
            if has_more is False:
                break
            if pages_count is not None and page >= pages_count:
                break
            if not page_items or len(page_items) < page_size:
                break

        return all_items

    def fetch_endpoint_items(self) -> list[dict[str, Any]]:
        """Fetch inventory endpoint items; kept as a convenience for callers."""
        return filter_endpoint_items(self.fetch_inventory_items())

    def request_json(self, payload: Mapping[str, Any]) -> Any:
        """POST one JSON-RPC payload to the Bitdefender Network API."""
        body = json.dumps(payload).encode("utf-8")
        request = urllib.request.Request(
            self.api_url,
            data=body,
            headers={
                "Authorization": self._authorization_header(),
                "Content-Type": "application/json",
                "Accept": "application/json",
                "User-Agent": self.user_agent,
            },
            method="POST",
        )

        last_error: Exception | None = None
        for attempt in range(3):
            try:
                with self._urlopen(request, timeout=self.timeout) as response:
                    return json.loads(response.read().decode("utf-8"))
            except urllib.error.HTTPError as exc:
                if exc.code not in TRANSIENT_HTTP_CODES:
                    detail = exc.read().decode("utf-8", errors="replace")
                    raise RuntimeError(f"Bitdefender API request failed with HTTP {exc.code}: {detail}") from exc
                last_error = exc
            except (TimeoutError, urllib.error.URLError) as exc:
                last_error = exc

            if attempt < 2:
                self._sleep(2**attempt)

        raise RuntimeError(f"Bitdefender API request failed after retries: {last_error}") from last_error

    def _request_payload(self, page: int) -> dict[str, Any]:
        params: dict[str, Any] = {
            "page": page,
            "perPage": self.page_size,
            "options": {
                "companies": {
                    "returnAllProducts": True,
                },
                "endpoints": {
                    "returnProductOutdated": self.return_product_outdated,
                    "includeScanLogs": self.include_scan_logs,
                },
            },
            "filters": {
                "type": {
                    "companies": True,
                    "computers": True,
                    "virtualMachines": True,
                    "ec2Instances": True,
                },
            },
        }
        if self.parent_id:
            params["parentId"] = self.parent_id
        if self.recursive:
            params["filters"]["depth"] = {"allItemsRecursively": True}

        return {
            "jsonrpc": "2.0",
            "method": "getNetworkInventoryItems",
            "params": params,
            "id": str(uuid4()),
        }

    def _custom_groups_payload(self) -> dict[str, Any]:
        return {
            "jsonrpc": "2.0",
            "method": "getCustomGroupsList",
            "params": {"parentId": self.parent_id or None},
            "id": str(uuid4()),
        }

    def _deleted_folder_request_payload(self, deleted_group_id: str, page: int) -> dict[str, Any]:
        params: dict[str, Any] = {
            "parentId": deleted_group_id,
            "page": page,
            "perPage": DELETED_FOLDER_PAGE_SIZE,
            "options": {
                "endpoints": {
                    "returnProductOutdated": self.return_product_outdated,
                    "includeScanLogs": self.include_scan_logs,
                },
            },
            "filters": {
                "type": {
                    "computers": True,
                    "virtualMachines": True,
                    "ec2Instances": True,
                },
                "depth": {"allItemsRecursively": True},
            },
        }
        return {
            "jsonrpc": "2.0",
            "method": "getNetworkInventoryItems",
            "params": params,
            "id": str(uuid4()),
        }

    def _authorization_header(self) -> str:
        token = base64.b64encode(f"{self.api_key}:".encode("utf-8")).decode("ascii")
        return f"Basic {token}"


def extract_jsonrpc_result(payload: Any) -> Any:
    """Return the JSON-RPC result value or raise a clear API error."""
    if not isinstance(payload, dict):
        raise ValueError("Bitdefender API response must be a JSON object.")

    error = payload.get("error")
    if error:
        if isinstance(error, dict):
            detail = error.get("message") or error.get("data") or error
        else:
            detail = error
        raise RuntimeError(f"Bitdefender API returned an error: {detail}")

    if "result" not in payload:
        raise ValueError("Bitdefender API response is missing a result value.")
    return payload.get("result")


def extract_result(payload: Any) -> dict[str, Any]:
    """Return the JSON-RPC result object or raise a clear API error."""
    result = extract_jsonrpc_result(payload)
    if not isinstance(result, dict):
        raise ValueError("Bitdefender API response is missing a result object.")
    return result


def extract_custom_group_items(result: Any) -> list[dict[str, Any]]:
    """Return custom group dictionaries from known getCustomGroupsList shapes."""
    if isinstance(result, list):
        return [item for item in result if isinstance(item, dict)]

    if not isinstance(result, Mapping):
        return []

    for key in ("items", "groups", "customGroups", "data"):
        items = result.get(key)
        if isinstance(items, list):
            return [item for item in items if isinstance(item, dict)]

    if result.get("id") and result.get("name"):
        return [dict(result)]
    return []


def find_deleted_group_id(groups: list[dict[str, Any]]) -> str:
    """Find the custom group named Deleted and return its ID."""
    for group in groups:
        if clean_display(group.get("name")) != DELETED_FOLDER_NAME:
            continue
        deleted_group_id = clean_display(group.get("id"))
        if deleted_group_id:
            return deleted_group_id
    return ""


def extract_inventory_items(result: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Return getNetworkInventoryItems items from a result object."""
    items = result.get("items")
    if not isinstance(items, list):
        raise ValueError("Bitdefender API result is missing an items list.")
    return [item for item in items if isinstance(item, dict)]


def extract_endpoint_items(result: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Return endpoint inventory items from a getNetworkInventoryItems result object."""
    return filter_endpoint_items(extract_inventory_items(result))


def inventory_item_details(item: Mapping[str, Any]) -> Mapping[str, Any]:
    details = item.get("details")
    return details if isinstance(details, Mapping) else {}


def is_item_in_deleted_folder(item: Mapping[str, Any], deleted_group_id: str = "") -> bool:
    """Return whether an inventory item is known to be inside the Deleted folder."""
    deleted_group_id = clean_display(deleted_group_id)
    if item.get("isInDeletedFolder") is True:
        return True

    if not deleted_group_id:
        return False

    details = inventory_item_details(item)
    return (
        clean_display(item.get("parentId")) == deleted_group_id
        or clean_display(details.get("groupId")) == deleted_group_id
    )


def mark_deleted_folder_item(item: Mapping[str, Any]) -> dict[str, Any]:
    """Return an inventory item copy marked as coming from the Deleted folder."""
    output = dict(item)
    output["isInDeletedFolder"] = True
    return output


def mark_deleted_folder_membership(
    item: Mapping[str, Any],
    deleted_group_id: str = "",
) -> dict[str, Any]:
    """Return an inventory item copy with Deleted-folder membership normalized."""
    output = dict(item)
    if is_item_in_deleted_folder(output, deleted_group_id):
        output["isInDeletedFolder"] = True
    return output


def merge_inventory_items(
    inventory_items: Sequence[dict[str, Any]],
    deleted_folder_items: Sequence[dict[str, Any]],
    deleted_group_id: str = "",
) -> list[dict[str, Any]]:
    """Merge regular inventory and Deleted-folder endpoint queries by item ID."""
    output: list[dict[str, Any]] = []
    items_by_id: dict[str, dict[str, Any]] = {}

    for item in inventory_items:
        copied = mark_deleted_folder_membership(item, deleted_group_id)
        item_id = clean_display(copied.get("id"))
        output.append(copied)
        if item_id:
            items_by_id[item_id] = copied

    for item in deleted_folder_items:
        copied = mark_deleted_folder_item(item)
        item_id = clean_display(copied.get("id"))
        if item_id and item_id in items_by_id:
            items_by_id[item_id]["isInDeletedFolder"] = True
            continue
        output.append(copied)
        if item_id:
            items_by_id[item_id] = copied

    return output


def filter_endpoint_items(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Return inventory items representing endpoint devices."""
    return [item for item in items if clean_display(item.get("type")) in ENDPOINT_ITEM_TYPE_KEYS]


def filter_export_endpoint_items(
    items: list[dict[str, Any]],
    *,
    include_unprotected: bool = False,
) -> list[dict[str, Any]]:
    """Return endpoint inventory items that should count as BD-installed endpoints."""
    endpoint_items = filter_endpoint_items(items)
    if include_unprotected:
        return endpoint_items

    return [item for item in endpoint_items if is_export_protected_endpoint_item(item)]


def is_export_protected_endpoint_item(item: Mapping[str, Any]) -> bool:
    """Return whether an inventory endpoint should be exported by default."""
    details = item.get("details")
    if not isinstance(details, Mapping):
        return False

    managed_with_best = details.get("managedWithBest")
    if managed_with_best is True:
        return True
    if managed_with_best is False:
        return False

    return details.get("isManaged") is True


def build_company_names_by_id(items: list[dict[str, Any]]) -> dict[str, str]:
    """Build a company id to company name map from inventory company items."""
    output: dict[str, str] = {}
    for item in items:
        if clean_display(item.get("type")) != COMPANY_ITEM_TYPE_KEY:
            continue
        item_id = clean_display(item.get("id"))
        name = clean_display(item.get("name"))
        if item_id and name:
            output[item_id] = name
    return output


def extract_int(payload: Mapping[str, Any], key: str) -> int | None:
    value = payload.get(key)
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None
