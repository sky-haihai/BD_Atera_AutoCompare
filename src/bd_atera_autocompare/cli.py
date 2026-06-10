from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from pathlib import Path

from .pipeline import (
    DEFAULT_ATERA_OUTPUT_PATH,
    DEFAULT_ATERA_PAGE_SIZE,
    DEFAULT_BD_API_URL,
    DEFAULT_BD_OUTPUT_PATH,
    DEFAULT_BD_PAGE_SIZE,
    DEFAULT_COMPANY_ALIASES_PATH,
    DEFAULT_COMPARE_OUTPUT_PATH,
    DEFAULT_DEVICE_ALIASES_PATH,
    DEFAULT_DUPLICATES_OUTPUT_PATH,
    PipelineResult,
    PipelineSettings,
    bd_provider_from_settings,
    run_pipeline,
)


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run one full Atera pull, Bitdefender pull, and comparison.",
    )
    parser.add_argument(
        "--env-file",
        type=Path,
        default=Path(".env"),
        help="Path to the local .env file used for Atera and BD credentials. Default: .env.",
    )
    parser.add_argument(
        "--http-timeout",
        type=float,
        default=30.0,
        help="HTTP timeout in seconds for both API pulls. Default: 30.",
    )
    parser.add_argument(
        "--atera-output",
        type=Path,
        default=DEFAULT_ATERA_OUTPUT_PATH,
        help=f"Path to write the normalized Atera CSV. Default: {DEFAULT_ATERA_OUTPUT_PATH}.",
    )
    parser.add_argument(
        "--atera-page-size",
        type=int,
        default=DEFAULT_ATERA_PAGE_SIZE,
        help=f"Atera API page size. Default: {DEFAULT_ATERA_PAGE_SIZE}.",
    )
    parser.add_argument(
        "--bd-output",
        type=Path,
        default=DEFAULT_BD_OUTPUT_PATH,
        help=f"Path to write the normalized BD CSV. Default: {DEFAULT_BD_OUTPUT_PATH}.",
    )
    parser.add_argument(
        "--bd-api-url",
        default="",
        help=f"Bitdefender Network API JSON-RPC URL. Default: {DEFAULT_BD_API_URL}.",
    )
    parser.add_argument(
        "--bd-page-size",
        type=int,
        default=DEFAULT_BD_PAGE_SIZE,
        help=f"Bitdefender API page size. Default: {DEFAULT_BD_PAGE_SIZE}.",
    )
    parser.add_argument(
        "--bd-parent-id",
        default="",
        help="Optional Bitdefender company or group ID passed as getNetworkInventoryItems parentId.",
    )
    parser.add_argument(
        "--bd-company-name",
        default="",
        help="Optional company name to stamp onto BD rows when inventory companyId cannot be resolved.",
    )
    parser.add_argument(
        "--bd-no-recursive",
        action="store_true",
        help="Do not set filters.depth.allItemsRecursively=true in getNetworkInventoryItems.",
    )
    parser.add_argument(
        "--bd-no-product-outdated",
        action="store_true",
        help="Do not request the productOutdated option from Bitdefender.",
    )
    parser.add_argument(
        "--bd-no-scan-logs",
        action="store_true",
        help="Do not request the lastSuccessfulScan option from Bitdefender.",
    )
    parser.add_argument(
        "--bd-include-unprotected",
        action="store_true",
        help=(
            "Compatibility option; BD CSV now includes all endpoint inventory and compare decides how to use it."
        ),
    )
    parser.add_argument(
        "--report-output",
        type=Path,
        default=DEFAULT_COMPARE_OUTPUT_PATH,
        help=f"Path to write the mismatch report CSV. Default: {DEFAULT_COMPARE_OUTPUT_PATH}.",
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
    return parser.parse_args(argv)


def settings_from_args(args: argparse.Namespace) -> PipelineSettings:
    return PipelineSettings(
        env_file=args.env_file,
        http_timeout=args.http_timeout,
        atera_output=args.atera_output,
        atera_page_size=args.atera_page_size,
        bd_output=args.bd_output,
        bd_api_url=args.bd_api_url,
        bd_page_size=args.bd_page_size,
        bd_parent_id=args.bd_parent_id,
        bd_company_name=args.bd_company_name,
        bd_recursive=not args.bd_no_recursive,
        bd_return_product_outdated=not args.bd_no_product_outdated,
        bd_include_scan_logs=not args.bd_no_scan_logs,
        bd_include_unprotected=args.bd_include_unprotected,
        report_output=args.report_output,
        duplicates_output=args.duplicates_output,
        company_aliases=args.company_aliases,
        device_aliases=args.device_aliases,
    )


def bd_provider_from_args(args: argparse.Namespace):
    return bd_provider_from_settings(settings_from_args(args))


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        result = run_pipeline(settings_from_args(args))
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    print(f"Wrote {result.atera_rows} Atera row(s) to {result.atera_output}")
    print(f"Wrote {result.bd_rows} BD row(s) to {result.bd_output}")
    print(f"Wrote {result.mismatch_rows} mismatch row(s) to {result.report_output}")
    print(f"Wrote duplicate entry details to {result.duplicates_output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
