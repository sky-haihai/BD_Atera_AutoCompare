from __future__ import annotations

import csv
import io
import os
import sys
import tempfile
import unittest
from contextlib import redirect_stderr
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from bd_atera_autocompare.bd import mapping as bd_mapping
from bd_atera_autocompare.bd import prepare as bd_prepare
from bd_atera_autocompare.bd import schema as bd_schema


def write_report(path: Path, rows: list[dict[str, str]]) -> None:
    fieldnames = [
        "Endpoint Name",
        "Endpoint FQDN",
        "IP",
        "Update Status",
        "Last Update",
        "Antimalware",
        "Managed",
        "Online",
        "Company Name",
        "Container Host",
    ]
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def report_row(
    endpoint_name: str = "  PC01  ",
    company_name: str = "  Acme  ",
    ip_address: str = "10.0.0.1",
    online: str = "Online",
    update_status: str = "Updated",
    last_update: str = "04 June 2026, 09:44:47",
) -> dict[str, str]:
    return {
        "Endpoint Name": endpoint_name,
        "Endpoint FQDN": "pc01",
        "IP": ip_address,
        "Update Status": update_status,
        "Last Update": last_update,
        "Antimalware": "On",
        "Managed": "Yes",
        "Online": online,
        "Company Name": company_name,
        "Container Host": "N/A",
    }


class BdPrepareTests(unittest.TestCase):
    def test_map_bd_report_row_uses_real_report_headers(self) -> None:
        row = bd_mapping.map_bd_report_row(
            report_row(
                endpoint_name="  DESKTOP-J6QIIND(Datatrasfer to Alison)  ",
                company_name="  Acme  ",
            ),
            row_number=2,
        )

        self.assertEqual(row.device_name, "DESKTOP-J6QIIND(Datatrasfer to Alison)")
        self.assertEqual(row.company_name, "Acme")
        self.assertEqual(row.ip_address, "10.0.0.1")
        self.assertEqual(row.status, "Online")
        self.assertEqual(row.last_seen, "")
        self.assertEqual(row.bd_row_number, "2")
        self.assertEqual(
            row.to_csv_row(),
            {
                "Device Name": "DESKTOP-J6QIIND(Datatrasfer to Alison)",
                "Company Name": "Acme",
                "IP Address": "10.0.0.1",
                "Status": "Online",
                "Last Seen": "",
                "BD Row Number": "2",
            },
        )

    def test_convert_bd_online_status_treats_report_timestamp_as_offline(self) -> None:
        self.assertEqual(
            bd_mapping.convert_bd_online_status("16 April 2026, 09:30:46"),
            "Offline",
        )
        self.assertEqual(bd_mapping.convert_bd_online_status("Unmanaged"), "Unmanaged")
        self.assertEqual(bd_mapping.convert_bd_online_status("", "Updated"), "Updated")

    def test_last_seen_comes_from_offline_online_timestamp(self) -> None:
        row = bd_mapping.map_bd_report_row(
            report_row(online="16 April 2026, 09:30:46", last_update="16 April 2026, 07:43:21"),
            row_number=9,
        )

        self.assertEqual(row.status, "Offline")
        self.assertEqual(row.last_seen, "16 April 2026, 09:30:46")

    def test_manual_provider_validates_required_report_headers(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            report = Path(tmp) / "bd.csv"
            report.write_text("Endpoint Name,Company Name,IP,Online\nPC01,Acme,10.0.0.1,Online\n", encoding="utf-8")

            provider = bd_prepare.ManualBdReportProvider(report)

            with self.assertRaisesRegex(ValueError, "Update Status"):
                provider.get_rows()

    def test_manual_provider_preserves_source_line_number_and_skips_blank_rows(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            report = Path(tmp) / "bd.csv"
            report.write_text(
                "Endpoint Name,Endpoint FQDN,IP,Update Status,Last Update,Antimalware,Managed,Online,Company Name,Container Host\n"
                "PC01,pc01,10.0.0.1,Updated,\"04 June 2026, 09:44:47\",On,Yes,Online,Acme,N/A\n"
                ",,,,,,,,,\n"
                "PC02,pc02,10.0.0.2,Unknown,\"16 April 2026, 07:43:21\",Unknown,Yes,\"16 April 2026, 09:30:46\",Acme,N/A\n",
                encoding="utf-8-sig",
            )

            rows = bd_prepare.ManualBdReportProvider(report).get_rows()

        self.assertEqual([row.device_name for row in rows], ["PC01", "PC02"])
        self.assertEqual([row.bd_row_number for row in rows], ["2", "4"])

    def test_write_bd_csv_creates_directory_and_preserves_column_order(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "data" / "bd_endpoint_status.csv"
            bd_schema.write_bd_csv(output, [bd_mapping.map_bd_report_row(report_row(), 2)])

            with output.open("r", encoding="utf-8-sig", newline="") as handle:
                reader = csv.DictReader(handle)
                rows = list(reader)

        self.assertEqual(reader.fieldnames, bd_schema.BD_CSV_COLUMNS)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["Device Name"], "PC01")

    def test_prepare_bd_csv_writes_provider_rows(self) -> None:
        class FakeProvider:
            def get_rows(self) -> list[bd_schema.BdNormalizedRow]:
                return [bd_schema.BdNormalizedRow(device_name="PC01", company_name="Acme", bd_row_number="2")]

        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "bd.csv"
            count = bd_prepare.prepare_bd_csv(FakeProvider(), output)

        self.assertEqual(count, 1)

    def test_parse_args_keeps_report_source_as_default(self) -> None:
        args = bd_prepare.parse_args([])

        self.assertEqual(args.source, "report")
        self.assertEqual(args.output, bd_prepare.DEFAULT_BD_OUTPUT_PATH)
        self.assertEqual(args.input_dir, bd_prepare.DEFAULT_INPUT_DIR)

    def test_latest_report_csv_uses_newest_csv_from_input_dir(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            input_dir = Path(tmp) / "input"
            input_dir.mkdir()
            older = input_dir / "older.csv"
            newer = input_dir / "newer.csv"
            write_report(older, [report_row(endpoint_name="OLDER")])
            write_report(newer, [report_row(endpoint_name="NEWER")])
            os.utime(older, (100, 100))
            os.utime(newer, (200, 200))

            latest = bd_prepare.find_latest_report_csv(input_dir)

        self.assertEqual(latest.name, "newer.csv")

    def test_latest_report_csv_fails_when_input_dir_has_no_csv(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaisesRegex(FileNotFoundError, "No CSV"):
                bd_prepare.find_latest_report_csv(Path(tmp) / "input")

    def test_main_uses_latest_input_csv_when_report_path_is_not_provided(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            input_dir = Path(tmp) / "input"
            input_dir.mkdir()
            older = input_dir / "older.csv"
            newer = input_dir / "newer.csv"
            output = Path(tmp) / "out" / "bd.csv"
            write_report(older, [report_row(endpoint_name="OLDER")])
            write_report(newer, [report_row(endpoint_name="NEWER")])
            os.utime(older, (100, 100))
            os.utime(newer, (200, 200))

            exit_code = bd_prepare.main(["--input-dir", str(input_dir), "--output", str(output)])

            with output.open("r", encoding="utf-8-sig", newline="") as handle:
                rows = list(csv.DictReader(handle))

        self.assertEqual(exit_code, 0)
        self.assertEqual(rows[0]["Device Name"], "NEWER")

    def test_main_fails_when_default_report_input_has_no_csv(self) -> None:
        stderr = io.StringIO()
        with redirect_stderr(stderr):
            exit_code = bd_prepare.main(["--input-dir", "missing-input-dir"])

        self.assertEqual(exit_code, 1)
        self.assertIn("No CSV", stderr.getvalue())

    def test_api_source_is_kept_as_explicit_unimplemented_argument(self) -> None:
        stderr = io.StringIO()
        with redirect_stderr(stderr):
            exit_code = bd_prepare.main(["--source", "api"])

        self.assertEqual(exit_code, 1)
        self.assertIn("not implemented", stderr.getvalue())

    def test_main_writes_normalized_report_output(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            report = Path(tmp) / "report.csv"
            output = Path(tmp) / "out" / "bd.csv"
            write_report(report, [report_row()])

            exit_code = bd_prepare.main(["--bd-report", str(report), "--output", str(output)])

            with output.open("r", encoding="utf-8-sig", newline="") as handle:
                rows = list(csv.DictReader(handle))

        self.assertEqual(exit_code, 0)
        self.assertEqual(rows[0]["Device Name"], "PC01")
        self.assertEqual(rows[0]["BD Row Number"], "2")


if __name__ == "__main__":
    unittest.main()
