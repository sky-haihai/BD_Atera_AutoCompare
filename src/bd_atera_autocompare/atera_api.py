from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Any

from .env_file import load_env_file
from .atera_mapping import map_raw_agent
from .atera_schema import AteraNormalizedRow
from .normalization import clean_display


DEFAULT_ATERA_BASE_URL = "https://app.atera.com/api/v3"
DEFAULT_PAGE_SIZE = 100
MAX_ATERA_PAGES = 1000
TRANSIENT_HTTP_CODES = {429, 500, 502, 503, 504}


class AteraApiProvider:
    def __init__(
        self,
        api_key: str,
        *,
        base_url: str = DEFAULT_ATERA_BASE_URL,
        timeout: float = 30.0,
        page_size: int = DEFAULT_PAGE_SIZE,
        max_pages: int = MAX_ATERA_PAGES,
        urlopen: Callable[..., Any] | None = None,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        """Configure the Atera API provider and validate required credentials."""
        self.api_key = clean_display(api_key)
        if not self.api_key:
            raise ValueError("ATERA_API_KEY is required.")

        self.base_url = (clean_display(base_url) or DEFAULT_ATERA_BASE_URL).rstrip("/")
        self.timeout = timeout
        self.page_size = page_size
        self.max_pages = max_pages
        self._urlopen = urlopen or urllib.request.urlopen
        self._sleep = sleep

    @classmethod
    def from_environment(
        cls,
        environ: Mapping[str, str] | None = None,
        env_file: str | Path | None = ".env",
        **kwargs: Any,
    ) -> AteraApiProvider:
        """Build a provider from local .env values with process environment fallback."""
        process_env = os.environ if environ is None else environ
        file_env = load_env_file(env_file) if env_file is not None else {}
        return cls(
            api_key=file_env.get("ATERA_API_KEY") or process_env.get("ATERA_API_KEY", ""),
            base_url=file_env.get("ATERA_BASE_URL") or process_env.get("ATERA_BASE_URL", DEFAULT_ATERA_BASE_URL),
            **kwargs,
        )

    def get_rows(self) -> list[AteraNormalizedRow]:
        """Fetch raw agents and map them to normalized Atera rows."""
        return [map_raw_agent(agent) for agent in self.fetch_raw_agents()]

    def fetch_raw_agents(self) -> list[dict[str, Any]]:
        """Fetch all available Atera agent pages as raw API dictionaries."""
        all_agents: list[dict[str, Any]] = []
        seen_page_signatures: set[str] = set()

        for page in range(1, self.max_pages + 1):
            payload = self.request_json(self._agents_url(page))
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

            if len(page_agents) < self.page_size:
                break

        return all_agents

    def request_json(self, url: str) -> Any:
        """Request one JSON payload from Atera with limited transient retries."""
        request = urllib.request.Request(
            url,
            headers={"X-API-KEY": self.api_key, "Accept": "application/json"},
            method="GET",
        )

        last_error: Exception | None = None
        for attempt in range(3):
            try:
                with self._urlopen(request, timeout=self.timeout) as response:
                    body = response.read().decode("utf-8")
                    return json.loads(body)
            except urllib.error.HTTPError as exc:
                if exc.code not in TRANSIENT_HTTP_CODES:
                    detail = exc.read().decode("utf-8", errors="replace")
                    raise RuntimeError(f"Atera API request failed with HTTP {exc.code}: {detail}") from exc
                last_error = exc
            except (TimeoutError, urllib.error.URLError) as exc:
                last_error = exc

            if attempt < 2:
                self._sleep(2**attempt)

        raise RuntimeError(f"Atera API request failed after retries: {last_error}") from last_error

    def _agents_url(self, page: int) -> str:
        """Build the paged Atera agents endpoint URL for a one-based page number."""
        query = urllib.parse.urlencode({"page": page, "itemsInPage": self.page_size})
        return f"{self.base_url}/agents?{query}"


def extract_agent_items(payload: Any) -> list[dict[str, Any]]:
    """Find the agent list inside common Atera API response shapes."""
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]

    if not isinstance(payload, dict):
        raise ValueError("Atera API response must be a JSON object or array.")

    for key in ["items", "Items", "data", "Data", "agents", "Agents", "value", "Value"]:
        value = payload.get(key)
        if isinstance(value, list):
            return [item for item in value if isinstance(item, dict)]

    dict_lists = [
        value
        for value in payload.values()
        if isinstance(value, list) and all(isinstance(item, dict) for item in value)
    ]
    if len(dict_lists) == 1:
        return dict_lists[0]

    raise ValueError("Could not find the agents list in the Atera API response.")


def extract_int(payload: Any, keys: Sequence[str]) -> int | None:
    """Extract an integer metadata value from a JSON object using possible key names."""
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
