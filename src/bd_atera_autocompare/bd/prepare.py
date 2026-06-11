from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from pathlib import Path

DEFAULT_OUTPUT_PATH = Path("output/bd_endpoint_status.csv")
DEFAULT_BD_OUTPUT_PATH = DEFAULT_OUTPUT_PATH

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
    from bd_atera_autocompare.bd.api import (
        DEFAULT_BD_API_URL,
        DEFAULT_BD_USER_AGENT,
        DEFAULT_PAGE_SIZE,
        MAX_BD_PAGES,
        BdApiProvider,
        build_company_names_by_id,
        extract_endpoint_items,
        extract_inventory_items,
        extract_result,
        filter_export_endpoint_items,
        filter_endpoint_items,
    )
    from bd_atera_autocompare.bd.mapping import (
        bool_display,
        endpoint_status,
        join_display_values,
        map_inventory_endpoint_item,
    )
    from bd_atera_autocompare.bd.schema import (
        BD_CSV_COLUMNS,
        BdNormalizedRow,
        BdProvider,
        write_bd_csv,
    )
else:
    from .api import (
        DEFAULT_BD_API_URL,
        DEFAULT_BD_USER_AGENT,
        DEFAULT_PAGE_SIZE,
        MAX_BD_PAGES,
        BdApiProvider,
        build_company_names_by_id,
        extract_endpoint_items,
        extract_inventory_items,
        extract_result,
        filter_export_endpoint_items,
        filter_endpoint_items,
    )
    from .mapping import (
        bool_display,
        endpoint_status,
        join_display_values,
        map_inventory_endpoint_item,
    )
    from .schema import (
        BD_CSV_COLUMNS,
        BdNormalizedRow,
        BdProvider,
        write_bd_csv,
    )

__all__ = [
    "BD_CSV_COLUMNS",
    "DEFAULT_BD_API_URL",
    "DEFAULT_BD_OUTPUT_PATH",
    "DEFAULT_BD_USER_AGENT",
    "DEFAULT_OUTPUT_PATH",
    "DEFAULT_PAGE_SIZE",
    "MAX_BD_PAGES",
    "BdApiProvider",
    "BdNormalizedRow",
    "BdProvider",
    "bool_display",
    "build_company_names_by_id",
    "endpoint_status",
    "extract_endpoint_items",
    "extract_inventory_items",
    "extract_result",
    "filter_export_endpoint_items",
    "filter_endpoint_items",
    "join_display_values",
    "main",
    "map_inventory_endpoint_item",
    "parse_args",
    "prepare_bd_csv",
    "write_bd_csv",
]


def prepare_bd_csv(provider: BdProvider, output_path: str | Path = DEFAULT_OUTPUT_PATH) -> int:
    """Run a BD provider and write the normalized CSV output."""
    rows = provider.get_rows()
    write_bd_csv(output_path, rows)
    return len(rows)


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    """Parse command-line options for the BD prepare command."""
    parser = argparse.ArgumentParser(description="Export normalized Bitdefender getNetworkInventoryItems CSV.")
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_OUTPUT_PATH,
        help=f"Path to write the normalized BD CSV. Default: {DEFAULT_OUTPUT_PATH}.",
    )
    parser.add_argument(
        "--env-file",
        type=Path,
        default=Path(".env"),
        help="Path to the local .env file. Default: .env.",
    )
    parser.add_argument(
        "--api-url",
        default="",
        help=f"Bitdefender Network API JSON-RPC URL. Default: {DEFAULT_BD_API_URL}.",
    )
    parser.add_argument(
        "--http-timeout",
        type=float,
        default=30.0,
        help="Bitdefender API HTTP timeout in seconds. Default: 30.",
    )
    parser.add_argument(
        "--page-size",
        type=int,
        default=DEFAULT_PAGE_SIZE,
        help=f"Bitdefender API page size. Default: {DEFAULT_PAGE_SIZE}.",
    )
    parser.add_argument(
        "--parent-id",
        default="",
        help="Optional Bitdefender company or group ID passed as getNetworkInventoryItems parentId.",
    )
    parser.add_argument(
        "--company-name",
        default="",
        help="Optional company name to stamp onto rows when inventory companyId cannot be resolved.",
    )
    parser.add_argument(
        "--no-recursive",
        action="store_true",
        help="Do not set filters.depth.allItemsRecursively=true in getNetworkInventoryItems.",
    )
    parser.add_argument(
        "--no-product-outdated",
        action="store_true",
        help="Do not request the productOutdated option.",
    )
    parser.add_argument(
        "--no-scan-logs",
        action="store_true",
        help="Do not request the lastSuccessfulScan option.",
    )
    parser.add_argument(
        "--include-unprotected",
        action="store_true",
        help=(
            "Compatibility option; BD CSV now includes all endpoint inventory and compare decides how to use it."
        ),
    )
    return parser.parse_args(argv)


def provider_from_args(args: argparse.Namespace) -> BdProvider:
    """Build the selected BD provider from parsed CLI arguments."""
    provider_kwargs = {
        "env_file": args.env_file,
        "timeout": args.http_timeout,
        "page_size": args.page_size,
        "recursive": not args.no_recursive,
        "return_product_outdated": not args.no_product_outdated,
        "include_scan_logs": not args.no_scan_logs,
        "include_unprotected": args.include_unprotected,
    }
    if args.api_url:
        provider_kwargs["api_url"] = args.api_url
    if args.parent_id:
        provider_kwargs["parent_id"] = args.parent_id
    if args.company_name:
        provider_kwargs["company_name"] = args.company_name
    return BdApiProvider.from_environment(**provider_kwargs)


def main(argv: Sequence[str] | None = None) -> int:
    """CLI entry point for preparing normalized BD endpoint report data."""
    args = parse_args(argv)
    try:
        provider = provider_from_args(args)
        count = prepare_bd_csv(provider, args.output)
        print(f"Wrote {count} BD row(s) to {args.output}")
        return 0
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
