from __future__ import annotations

import argparse
import csv
import sys
from collections.abc import Sequence
from pathlib import Path

DEFAULT_OUTPUT_PATH = Path("data/bd_endpoint_status.csv")
DEFAULT_BD_OUTPUT_PATH = DEFAULT_OUTPUT_PATH
DEFAULT_INPUT_DIR = Path("input")
DEFAULT_BD_SOURCE = "report"

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
    from bd_atera_autocompare.bd.mapping import (
        BD_REPORT_REQUIRED_HEADERS,
        convert_bd_online_status,
        is_bd_report_timestamp,
        map_bd_last_seen,
        map_bd_report_row,
    )
    from bd_atera_autocompare.bd.schema import (
        BD_CSV_COLUMNS,
        BdNormalizedRow,
        BdProvider,
        write_bd_csv,
    )
    from bd_atera_autocompare.csv_io import require_headers
else:
    from .mapping import (
        BD_REPORT_REQUIRED_HEADERS,
        convert_bd_online_status,
        is_bd_report_timestamp,
        map_bd_last_seen,
        map_bd_report_row,
    )
    from .schema import (
        BD_CSV_COLUMNS,
        BdNormalizedRow,
        BdProvider,
        write_bd_csv,
    )
    from ..csv_io import require_headers

__all__ = [
    "BD_CSV_COLUMNS",
    "BD_REPORT_REQUIRED_HEADERS",
    "DEFAULT_BD_OUTPUT_PATH",
    "DEFAULT_BD_SOURCE",
    "DEFAULT_INPUT_DIR",
    "DEFAULT_OUTPUT_PATH",
    "BdApiProvider",
    "BdNormalizedRow",
    "BdProvider",
    "ManualBdReportProvider",
    "convert_bd_online_status",
    "is_bd_report_timestamp",
    "find_latest_report_csv",
    "main",
    "map_bd_last_seen",
    "map_bd_report_row",
    "parse_args",
    "prepare_bd_csv",
    "write_bd_csv",
]


class ManualBdReportProvider:
    def __init__(self, report_path: str | Path) -> None:
        self.report_path = Path(report_path)

    def get_rows(self) -> list[BdNormalizedRow]:
        """Read a manual Bitdefender report CSV and return normalized rows."""
        with self.report_path.open("r", encoding="utf-8-sig", newline="") as handle:
            reader = csv.DictReader(handle)
            require_headers(reader.fieldnames, BD_REPORT_REQUIRED_HEADERS, self.report_path)
            rows: list[BdNormalizedRow] = []
            for source_row in reader:
                if is_empty_source_row(source_row):
                    continue
                rows.append(map_bd_report_row(source_row, reader.line_num))
        return rows


class BdApiProvider:
    def get_rows(self) -> list[BdNormalizedRow]:
        """Placeholder for the future Bitdefender Reports API implementation."""
        raise NotImplementedError("Bitdefender Reports API source is not implemented yet. Use --source report.")


def is_empty_source_row(source_row: dict[str | None, object]) -> bool:
    """Return whether DictReader produced a row with no meaningful values."""
    return not any(str(value or "").strip() for key, value in source_row.items() if key is not None)


def find_latest_report_csv(input_dir: str | Path = DEFAULT_INPUT_DIR) -> Path:
    """Return the newest CSV file from the BD report input directory."""
    directory = Path(input_dir)
    candidates = [path for path in directory.glob("*.csv") if path.is_file()]
    if not candidates:
        raise FileNotFoundError(f"No CSV report files found in {directory}.")
    return max(candidates, key=lambda path: (path.stat().st_mtime_ns, path.name.casefold()))


def prepare_bd_csv(provider: BdProvider, output_path: str | Path = DEFAULT_OUTPUT_PATH) -> int:
    """Run a BD provider and write the normalized CSV output."""
    rows = provider.get_rows()
    write_bd_csv(output_path, rows)
    return len(rows)


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    """Parse command-line options for the BD prepare command."""
    parser = argparse.ArgumentParser(description="Prepare normalized Bitdefender endpoint CSV.")
    parser.add_argument(
        "--source",
        choices=("report", "api"),
        default=DEFAULT_BD_SOURCE,
        help=f"BD data source to use. Default: {DEFAULT_BD_SOURCE}.",
    )
    parser.add_argument(
        "--bd-report",
        type=Path,
        help=f"Path to the manually downloaded Bitdefender report CSV. Defaults to newest CSV in {DEFAULT_INPUT_DIR}.",
    )
    parser.add_argument(
        "--input-dir",
        type=Path,
        default=DEFAULT_INPUT_DIR,
        help=f"Folder containing manual Bitdefender report CSV files. Default: {DEFAULT_INPUT_DIR}.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_OUTPUT_PATH,
        help=f"Path to write the normalized BD CSV. Default: {DEFAULT_OUTPUT_PATH}.",
    )
    return parser.parse_args(argv)


def provider_from_args(args: argparse.Namespace) -> BdProvider:
    """Build the selected BD provider from parsed CLI arguments."""
    if args.source == "api":
        return BdApiProvider()

    if args.bd_report is None:
        return ManualBdReportProvider(find_latest_report_csv(args.input_dir))

    return ManualBdReportProvider(args.bd_report)


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
