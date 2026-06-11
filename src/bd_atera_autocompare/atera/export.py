from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from pathlib import Path

DEFAULT_OUTPUT_PATH = Path("output/atera_agents.csv")
DEFAULT_ATERA_OUTPUT_PATH = DEFAULT_OUTPUT_PATH

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
    from bd_atera_autocompare.atera.api import (
        DEFAULT_ATERA_BASE_URL,
        DEFAULT_ATERA_USER_AGENT,
        DEFAULT_PAGE_SIZE,
        MAX_ATERA_PAGES,
        AteraApiProvider,
        extract_agent_items,
        extract_int,
    )
    from bd_atera_autocompare.atera.mapping import convert_online_status, map_raw_agent
    from bd_atera_autocompare.atera.schema import (
        ATERA_CSV_COLUMNS,
        AteraNormalizedRow,
        AteraProvider,
        validate_normalized_rows,
        write_atera_csv,
    )
else:
    from .api import (
        DEFAULT_ATERA_BASE_URL,
        DEFAULT_ATERA_USER_AGENT,
        DEFAULT_PAGE_SIZE,
        MAX_ATERA_PAGES,
        AteraApiProvider,
        extract_agent_items,
        extract_int,
    )
    from .mapping import convert_online_status, map_raw_agent
    from .schema import (
        ATERA_CSV_COLUMNS,
        AteraNormalizedRow,
        AteraProvider,
        validate_normalized_rows,
        write_atera_csv,
    )

__all__ = [
    "ATERA_CSV_COLUMNS",
    "DEFAULT_ATERA_BASE_URL",
    "DEFAULT_ATERA_OUTPUT_PATH",
    "DEFAULT_ATERA_USER_AGENT",
    "DEFAULT_OUTPUT_PATH",
    "DEFAULT_PAGE_SIZE",
    "MAX_ATERA_PAGES",
    "AteraApiProvider",
    "AteraNormalizedRow",
    "AteraProvider",
    "convert_online_status",
    "export_atera_csv",
    "extract_agent_items",
    "extract_int",
    "main",
    "map_raw_agent",
    "parse_args",
    "validate_normalized_rows",
    "write_atera_csv",
]


def export_atera_csv(provider: AteraProvider, output_path: str | Path = DEFAULT_OUTPUT_PATH) -> int:
    """Run an Atera provider and write the normalized CSV output."""
    rows = provider.get_rows()
    write_atera_csv(output_path, rows)
    return len(rows)


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    """Parse command-line options for the Atera export command."""
    parser = argparse.ArgumentParser(description="Export normalized Atera agents CSV.")
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_OUTPUT_PATH,
        help=f"Path to write the normalized Atera CSV. Default: {DEFAULT_OUTPUT_PATH}.",
    )
    parser.add_argument(
        "--http-timeout",
        type=float,
        default=30.0,
        help="Atera API HTTP timeout in seconds. Default: 30.",
    )
    parser.add_argument(
        "--page-size",
        type=int,
        default=DEFAULT_PAGE_SIZE,
        help=f"Atera API page size. Default: {DEFAULT_PAGE_SIZE}.",
    )
    parser.add_argument(
        "--env-file",
        type=Path,
        default=Path(".env"),
        help="Path to the local .env file. Default: .env.",
    )
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    """CLI entry point for exporting normalized Atera agent data."""
    args = parse_args(argv)
    try:
        provider = AteraApiProvider.from_environment(
            env_file=args.env_file,
            timeout=args.http_timeout,
            page_size=args.page_size,
        )
        count = export_atera_csv(provider, args.output)
        print(f"Wrote {count} Atera row(s) to {args.output}")
        return 0
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
