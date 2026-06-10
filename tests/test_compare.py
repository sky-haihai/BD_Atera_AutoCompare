from __future__ import annotations

import csv
import io
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from bd_atera_autocompare import compare
from bd_atera_autocompare.atera.schema import ATERA_CSV_COLUMNS
from bd_atera_autocompare.bd.schema import BD_CSV_COLUMNS


def atera_row(
    device_name: str = "PC01",
    company_name: str = "Acme",
    ip_address: str = "10.0.0.1",
    mac_addresses: str = "00:11:22:33:44:55",
    status: str = "Online",
    last_seen: str = "2026-06-09T19:55:34Z",
    agent_id: str = "A1",
) -> dict[str, str]:
    return {
        "Device Name": device_name,
        "Company Name": company_name,
        "IP Address": ip_address,
        "Reported From IP": "203.0.113.10",
        "MAC Addresses": mac_addresses,
        "Serial Number": "SN-123",
        "Status": status,
        "Last Seen": last_seen,
        "Atera Agent ID": agent_id,
        "Atera Machine ID": f"M-{agent_id}",
        "Atera Device GUID": f"G-{agent_id}",
    }


def bd_row(
    device_name: str = "PC01",
    company_name: str = "Acme",
    ip_address: str = "10.0.0.1",
    status: str = "Managed With BEST",
    last_seen: str = "",
    row_number: str = "2",
    endpoint_id: str = "bd-1",
    company_id: str = "company-1",
    parent_id: str = "group-1",
    network_item_type: str = "5",
    is_in_deleted_folder: str = "false",
    mac_addresses: str = "AA:BB:CC:DD:EE:FF",
    managed_with_best: str = "true",
    modules: str = "antimalware=true; firewall=false",
    last_successful_scan_date: str = "2026-06-09T19:55:34+00:00",
) -> dict[str, str]:
    return {
        "Device Name": device_name,
        "Company Name": company_name,
        "IP Address": ip_address,
        "Status": status,
        "Last Seen": last_seen,
        "BD Row Number": row_number,
        "BD Endpoint ID": endpoint_id,
        "BD Company ID": company_id,
        "Parent ID": parent_id,
        "Network Item Type": network_item_type,
        "Is In Deleted Folder": is_in_deleted_folder,
        "Label": "",
        "FQDN": "",
        "Group ID": "",
        "MAC Addresses": mac_addresses,
        "SSID": "",
        "Is Managed": "true",
        "Managed With BEST": managed_with_best,
        "Machine Type": "",
        "Operating System Version": "",
        "Is Container Host": "",
        "Managed Exchange Server": "",
        "Managed Relay": "",
        "Security Server": "",
        "Policy ID": "",
        "Policy Name": "",
        "Policy Applied": "",
        "Moving State": "",
        "Destination Company Name": "",
        "Product Outdated": "",
        "Last Successful Scan Name": "",
        "Last Successful Scan Date": last_successful_scan_date,
        "Modules": modules,
    }


def write_csv_file(path: Path, fieldnames: list[str], rows: list[dict[str, str]]) -> None:
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def read_report(path: Path) -> tuple[list[str] | None, list[dict[str, str]]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        rows = list(reader)
    return reader.fieldnames, rows


class CompareTests(unittest.TestCase):
    def run_compare(
        self,
        atera_rows: list[dict[str, str]],
        bd_rows: list[dict[str, str]],
        *,
        company_alias_rows: list[dict[str, str]] | None = None,
        device_alias_rows: list[dict[str, str]] | None = None,
    ) -> tuple[list[str] | None, list[dict[str, str]]]:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            atera_csv = tmp_path / "atera.csv"
            bd_csv = tmp_path / "bd.csv"
            output = tmp_path / "reports" / "mismatch.csv"
            duplicates_output = tmp_path / "reports" / "duplicates.csv"
            write_csv_file(atera_csv, ATERA_CSV_COLUMNS, atera_rows)
            write_csv_file(bd_csv, BD_CSV_COLUMNS, bd_rows)

            company_aliases = None
            if company_alias_rows is not None:
                company_aliases = tmp_path / "company_aliases.csv"
                write_csv_file(company_aliases, compare.COMPANY_ALIAS_COLUMNS, company_alias_rows)

            device_aliases = None
            if device_alias_rows is not None:
                device_aliases = tmp_path / "device_aliases.csv"
                write_csv_file(device_aliases, compare.DEVICE_ALIAS_COLUMNS, device_alias_rows)

            compare.compare_csvs(
                atera_csv=atera_csv,
                bd_csv=bd_csv,
                output=output,
                duplicates_output=duplicates_output,
                company_aliases=company_aliases,
                device_aliases=device_aliases,
            )
            return read_report(output)

    def test_exact_single_match_is_omitted_and_columns_are_stable(self) -> None:
        fieldnames, rows = self.run_compare([atera_row()], [bd_row()])

        self.assertEqual(fieldnames, compare.COMPARE_REPORT_COLUMNS)
        self.assertEqual(rows, [])

    def test_exact_single_match_with_no_best_outputs_missing_bd(self) -> None:
        _, rows = self.run_compare(
            [atera_row()],
            [bd_row(status="No BEST", managed_with_best="false", endpoint_id="bd-no-best")],
        )

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["Issue Type"], "Missing BD")
        self.assertEqual(rows[0]["Missing Software"], "Bitdefender Endpoint Protection")
        self.assertEqual(rows[0]["BD Endpoint IDs"], "bd-no-best")
        self.assertEqual(rows[0]["BD Company IDs"], "company-1")
        self.assertEqual(rows[0]["BD Parent IDs"], "group-1")
        self.assertEqual(rows[0]["BD Network Item Types"], "5")
        self.assertEqual(rows[0]["BD Modules"], "antimalware=true; firewall=false")
        self.assertEqual(rows[0]["BD Last Successful Scan Date"], "2026-06-09T19:55:34+00:00")
        self.assertEqual(rows[0]["Match Evidence"], "BD endpoint is not managed with BEST")

    def test_bd_deleted_folder_exact_match_is_treated_as_missing_bd(self) -> None:
        _, rows = self.run_compare(
            [atera_row()],
            [bd_row(endpoint_id="bd-deleted", is_in_deleted_folder="true")],
        )

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["Issue Type"], "Missing BD")
        self.assertEqual(rows[0]["BD Endpoint IDs"], "")
        self.assertEqual(rows[0]["Atera Device Name"], "PC01")

    def test_bd_deleted_folder_only_row_is_ignored(self) -> None:
        _, rows = self.run_compare(
            [],
            [bd_row(endpoint_id="bd-deleted", is_in_deleted_folder="true")],
        )

        self.assertEqual(rows, [])

    def test_unprotected_bd_only_row_is_ignored(self) -> None:
        _, rows = self.run_compare(
            [],
            [bd_row(status="No BEST", managed_with_best="false", endpoint_id="bd-no-best")],
        )

        self.assertEqual(rows, [])

    def test_case_and_space_normalization_omits_exact_match(self) -> None:
        _, rows = self.run_compare(
            [atera_row(device_name="  pc01  ", company_name="  acme  ")],
            [bd_row(device_name="PC01", company_name="ACME")],
        )

        self.assertEqual(rows, [])

    def test_company_alias_maps_atera_company_to_bd_company(self) -> None:
        _, rows = self.run_compare(
            [atera_row(company_name="Moore Equine Veterinary Centre - AR")],
            [bd_row(company_name="Moore Equine Veterinary Centre")],
            company_alias_rows=[
                {
                    "Atera Company Name": "Moore Equine Veterinary Centre - AR",
                    "BD Company Name": "Moore Equine Veterinary Centre",
                }
            ],
        )

        self.assertEqual(rows, [])

    def test_device_alias_is_scoped_by_canonical_company(self) -> None:
        _, rows = self.run_compare(
            [
                atera_row(device_name="PC01 (old)", company_name="Atera Acme", agent_id="A1"),
                atera_row(device_name="PC01 (old)", company_name="Other", agent_id="A2"),
            ],
            [
                bd_row(device_name="PC01", company_name="BD Acme", row_number="2"),
                bd_row(device_name="PC01", company_name="Other", row_number="3"),
            ],
            company_alias_rows=[{"Atera Company Name": "Atera Acme", "BD Company Name": "BD Acme"}],
            device_alias_rows=[
                {
                    "Company Name": "BD Acme",
                    "Raw Device Name": "PC01 (old)",
                    "Canonical Device Name": "PC01",
                }
            ],
        )

        self.assertEqual([row["Issue Type"] for row in rows], ["Missing Atera", "Missing BD"])
        self.assertEqual(rows[0]["Company Name"], "Other")
        self.assertEqual(rows[1]["Company Name"], "Other")

    def test_duplicate_detection_happens_after_aliasing(self) -> None:
        _, rows = self.run_compare(
            [
                atera_row(device_name="PC01 (old)", agent_id="A1"),
                atera_row(device_name="PC01", agent_id="A2"),
            ],
            [bd_row(device_name="PC01")],
            device_alias_rows=[
                {
                    "Company Name": "Acme",
                    "Raw Device Name": "PC01 (old)",
                    "Canonical Device Name": "PC01",
                }
            ],
        )

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["Issue Type"], "Duplicate Manual Review")
        self.assertEqual(rows[0]["Atera Count"], "2")
        self.assertEqual(rows[0]["BD Count"], "1")
        self.assertEqual(rows[0]["Alias Applied"], "Yes")

    def test_duplicate_entries_are_exported_to_detail_report(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            atera_csv = tmp_path / "atera.csv"
            bd_csv = tmp_path / "bd.csv"
            output = tmp_path / "mismatch.csv"
            duplicates_output = tmp_path / "duplicates.csv"
            write_csv_file(
                atera_csv,
                ATERA_CSV_COLUMNS,
                [
                    atera_row(device_name="PC01", agent_id="A1"),
                    atera_row(device_name="PC01", agent_id="A2"),
                ],
            )
            write_csv_file(
                bd_csv,
                BD_CSV_COLUMNS,
                [
                    bd_row(device_name="PC01", endpoint_id="bd-1", row_number="2"),
                    bd_row(device_name="PC01", endpoint_id="bd-2", row_number="3"),
                ],
            )

            compare.compare_csvs(
                atera_csv=atera_csv,
                bd_csv=bd_csv,
                output=output,
                duplicates_output=duplicates_output,
            )
            _, exception_rows = read_report(output)
            duplicate_fieldnames, duplicate_rows = read_report(duplicates_output)

        self.assertEqual([row["Issue Type"] for row in exception_rows], ["Duplicate Manual Review"])
        self.assertEqual(duplicate_fieldnames, compare.DUPLICATE_REPORT_COLUMNS)
        self.assertEqual(len(duplicate_rows), 4)
        self.assertEqual([row["Source"] for row in duplicate_rows], ["Atera", "Atera", "BD", "BD"])
        self.assertEqual({row["Duplicate Key"] for row in duplicate_rows}, {"Acme | PC01"})
        self.assertEqual({row["Atera Count"] for row in duplicate_rows}, {"2"})
        self.assertEqual({row["BD Count"] for row in duplicate_rows}, {"2"})
        self.assertEqual(
            [row["Atera Agent ID"] for row in duplicate_rows[:2]],
            ["A1", "A2"],
        )
        self.assertEqual(
            [row["BD Endpoint ID"] for row in duplicate_rows[2:]],
            ["bd-1", "bd-2"],
        )

    def test_duplicate_detail_report_sorts_by_company_and_device(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            atera_csv = tmp_path / "atera.csv"
            bd_csv = tmp_path / "bd.csv"
            output = tmp_path / "mismatch.csv"
            duplicates_output = tmp_path / "duplicates.csv"
            write_csv_file(
                atera_csv,
                ATERA_CSV_COLUMNS,
                [
                    atera_row(device_name="Z-PC", company_name="Zoo", agent_id="A1"),
                    atera_row(device_name="Z-PC", company_name="Zoo", agent_id="A2"),
                    atera_row(device_name="A-PC", company_name="Acme", agent_id="A3"),
                    atera_row(device_name="A-PC", company_name="Acme", agent_id="A4"),
                ],
            )
            write_csv_file(bd_csv, BD_CSV_COLUMNS, [])

            compare.compare_csvs(
                atera_csv=atera_csv,
                bd_csv=bd_csv,
                output=output,
                duplicates_output=duplicates_output,
            )
            _, duplicate_rows = read_report(duplicates_output)

        self.assertEqual(
            [(row["Company Name"], row["Canonical Device Name"]) for row in duplicate_rows],
            [("Acme", "A-PC"), ("Acme", "A-PC"), ("Zoo", "Z-PC"), ("Zoo", "Z-PC")],
        )

    def test_duplicate_key_with_mac_overlap_is_omitted(self) -> None:
        _, rows = self.run_compare(
            [
                atera_row(
                    device_name="DESKTOP-TMHPK4O",
                    company_name="Tanglefoot Veterinary Services (Cranbrook)",
                    ip_address="192.168.1.55",
                    mac_addresses="F0:D4:15:14:D3:95",
                    agent_id="A1",
                )
            ],
            [
                bd_row(
                    device_name="DESKTOP-TMHPK4O",
                    company_name="Tanglefoot Veterinary Services (Cranbrook)",
                    ip_address="192.168.1.120",
                    endpoint_id="bd-old-ip",
                    mac_addresses="f0d41514d395",
                ),
                bd_row(
                    device_name="DESKTOP-TMHPK4O",
                    company_name="Tanglefoot Veterinary Services (Cranbrook)",
                    ip_address="192.168.1.55",
                    endpoint_id="bd-current-ip",
                    mac_addresses="f0d41514d395",
                ),
            ],
        )

        self.assertEqual(rows, [])

    def test_duplicate_key_with_mac_overlap_is_exported_to_duplicate_report(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            atera_csv = tmp_path / "atera.csv"
            bd_csv = tmp_path / "bd.csv"
            output = tmp_path / "mismatch.csv"
            duplicates_output = tmp_path / "duplicates.csv"
            write_csv_file(
                atera_csv,
                ATERA_CSV_COLUMNS,
                [
                    atera_row(
                        device_name="DESKTOP-TMHPK4O",
                        company_name="Tanglefoot Veterinary Services",
                        ip_address="192.168.1.55",
                        mac_addresses="F0:D4:15:14:D3:95",
                        agent_id="A1",
                    )
                ],
            )
            write_csv_file(
                bd_csv,
                BD_CSV_COLUMNS,
                [
                    bd_row(
                        device_name="DESKTOP-TMHPK4O",
                        company_name="Tanglefoot Veterinary Services (Cranbrook)",
                        ip_address="192.168.1.120",
                        endpoint_id="bd-old-ip",
                        mac_addresses="f0d41514d395",
                    ),
                    bd_row(
                        device_name="DESKTOP-TMHPK4O",
                        company_name="Tanglefoot Veterinary Services (Cranbrook)",
                        ip_address="192.168.1.55",
                        endpoint_id="bd-current-ip",
                        mac_addresses="f0d41514d395",
                    ),
                ],
            )
            company_aliases = tmp_path / "company_aliases.csv"
            write_csv_file(
                company_aliases,
                compare.COMPANY_ALIAS_COLUMNS,
                [
                    {
                        "Atera Company Name": "Tanglefoot Veterinary Services",
                        "BD Company Name": "Tanglefoot Veterinary Services (Cranbrook)",
                    }
                ],
            )

            compare.compare_csvs(
                atera_csv=atera_csv,
                bd_csv=bd_csv,
                output=output,
                duplicates_output=duplicates_output,
                company_aliases=company_aliases,
            )
            _, mismatch_rows = read_report(output)
            _, duplicate_rows = read_report(duplicates_output)

        self.assertEqual(mismatch_rows, [])
        self.assertEqual(len(duplicate_rows), 3)
        self.assertEqual([row["Source"] for row in duplicate_rows], ["Atera", "BD", "BD"])
        self.assertEqual(
            {row["Duplicate Key"] for row in duplicate_rows},
            {"Tanglefoot Veterinary Services (Cranbrook) | DESKTOP-TMHPK4O"},
        )
        self.assertEqual([row["BD Endpoint ID"] for row in duplicate_rows[1:]], ["bd-old-ip", "bd-current-ip"])

    def test_atera_only_and_bd_only_output_missing_rows(self) -> None:
        _, rows = self.run_compare(
            [atera_row(device_name="PC01", ip_address="10.0.0.1")],
            [bd_row(device_name="SERVER02", ip_address="10.0.0.2")],
        )

        self.assertEqual([row["Issue Type"] for row in rows], ["Missing BD", "Missing Atera"])
        self.assertEqual(rows[0]["Missing Software"], "Bitdefender Endpoint Protection")
        self.assertEqual(rows[1]["Missing Software"], "Atera Agent")

    def test_exception_report_sorts_by_company_and_device(self) -> None:
        _, rows = self.run_compare(
            [
                atera_row(device_name="PC-Z", company_name="Zoo", ip_address="10.0.2.10", agent_id="A1"),
                atera_row(device_name="PC-C", company_name="Acme", ip_address="10.0.1.10", agent_id="A2"),
            ],
            [
                bd_row(device_name="PC-A", company_name="Zoo", ip_address="10.0.2.20", endpoint_id="bd-z"),
                bd_row(device_name="PC-A", company_name="Acme", ip_address="10.0.1.20", endpoint_id="bd-a"),
            ],
        )

        self.assertEqual(
            [(row["Company Name"], row["Canonical Device Name"]) for row in rows],
            [("Acme", "PC-A"), ("Acme", "PC-C"), ("Zoo", "PC-A"), ("Zoo", "PC-Z")],
        )

    def test_ipv4_overlap_and_name_similarity_outputs_potential_match(self) -> None:
        _, rows = self.run_compare(
            [atera_row(device_name="DESKTOP-ABC1", ip_address="10.0.0.1")],
            [bd_row(device_name="DESKTOP-ABC2", ip_address="10.0.0.1")],
        )

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["Issue Type"], "Potential Match Manual Review")
        self.assertEqual(rows[0]["Match Evidence"], "IPv4 overlap: 10.0.0.1")
        self.assertEqual(rows[0]["Name Similarity"], "92%")

    def test_potential_match_without_best_outputs_missing_bd(self) -> None:
        _, rows = self.run_compare(
            [atera_row(device_name="DESKTOP-ABC1", ip_address="10.0.0.1")],
            [
                bd_row(
                    device_name="DESKTOP-ABC2",
                    ip_address="10.0.0.1",
                    status="No BEST",
                    managed_with_best="false",
                    endpoint_id="bd-no-best",
                )
            ],
        )

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["Issue Type"], "Missing BD")
        self.assertIn("IPv4 overlap: 10.0.0.1", rows[0]["Match Evidence"])
        self.assertIn("BD endpoint is not managed with BEST", rows[0]["Match Evidence"])

    def test_mac_overlap_is_treated_as_same_device_and_omitted(self) -> None:
        _, rows = self.run_compare(
            [atera_row(device_name="RECEPTION-PC", ip_address="", agent_id="A1")],
            [
                bd_row(
                    device_name="OLD-LAPTOP",
                    ip_address="",
                    endpoint_id="bd-mac",
                    mac_addresses="00-11-22-33-44-55",
                )
            ],
        )

        self.assertEqual(rows, [])

    def test_mac_overlap_without_best_outputs_missing_bd(self) -> None:
        _, rows = self.run_compare(
            [atera_row(device_name="RECEPTION-PC", ip_address="", agent_id="A1")],
            [
                bd_row(
                    device_name="OLD-LAPTOP",
                    ip_address="",
                    status="No BEST",
                    endpoint_id="bd-mac",
                    mac_addresses="00-11-22-33-44-55",
                    managed_with_best="false",
                )
            ],
        )

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["Issue Type"], "Missing BD")
        self.assertIn("MAC overlap: 00:11:22:33:44:55", rows[0]["Match Evidence"])
        self.assertIn("BD endpoint is not managed with BEST", rows[0]["Match Evidence"])
        self.assertEqual(rows[0]["Atera MAC Addresses"], "00:11:22:33:44:55")
        self.assertEqual(rows[0]["BD MAC Addresses"], "00:11:22:33:44:55")
        self.assertEqual(rows[0]["BD Endpoint IDs"], "bd-mac")
        self.assertEqual(rows[0]["BD Company IDs"], "company-1")

    def test_cross_company_mac_overlap_is_treated_as_same_device_and_omitted(self) -> None:
        _, rows = self.run_compare(
            [
                atera_row(
                    device_name="HYPERV-01",
                    company_name="Tanglefoot Veterinary Services",
                    ip_address="192.168.1.221",
                    mac_addresses="4C:D9:8F:38:57:2A; 4C:D9:8F:38:57:29",
                    agent_id="A1",
                )
            ],
            [
                bd_row(
                    device_name="HYPERV-01",
                    company_name="Tanglefoot Veterinary Services (Cranbrook)",
                    ip_address="192.168.1.221",
                    endpoint_id="bd-tanglefoot",
                    mac_addresses="4cd98f385729",
                )
            ],
        )

        self.assertEqual(rows, [])

    def test_multiple_cross_company_mac_overlaps_are_omitted_when_any_bd_has_best(self) -> None:
        _, rows = self.run_compare(
            [
                atera_row(
                    device_name="LAPTOP-9IGK5B7P",
                    company_name="Bridgeland Vet Clinic Inc.",
                    ip_address="192.168.4.31",
                    mac_addresses="C8:B2:9B:28:CA:A3",
                    agent_id="A1",
                )
            ],
            [
                bd_row(
                    device_name="LAPTOP-9IGK5B7P",
                    company_name="Mosaic Veterinary Partners",
                    ip_address="192.168.1.72",
                    endpoint_id="bd-moved-old",
                    mac_addresses="c8b29b28caa3",
                    managed_with_best="false",
                    status="No BEST",
                ),
                bd_row(
                    device_name="LAPTOP-9IGK5B7P",
                    company_name="Bridgeland Veterinary Clinic",
                    ip_address="192.168.4.31",
                    endpoint_id="bd-moved-current",
                    mac_addresses="c8b29b28caa3",
                ),
            ],
        )

        self.assertEqual(rows, [])

    def test_ipv6_is_ignored_for_potential_match(self) -> None:
        _, rows = self.run_compare(
            [atera_row(device_name="DESKTOP-ABC1", ip_address="fe80::1")],
            [bd_row(device_name="DESKTOP-ABC2", ip_address="fe80::1")],
        )

        self.assertEqual([row["Issue Type"] for row in rows], ["Missing BD", "Missing Atera"])
        self.assertEqual(rows[0]["Atera IPv4"], "")
        self.assertEqual(rows[1]["BD IPv4"], "")

    def test_offline_last_seen_fallback_outputs_potential_match_within_window(self) -> None:
        _, rows = self.run_compare(
            [
                atera_row(
                    device_name="DESKTOP-ABC1",
                    ip_address="",
                    status="Offline",
                    last_seen="2026-06-09T19:55:34Z",
                )
            ],
            [
                bd_row(
                    device_name="DESKTOP-ABC2",
                    ip_address="",
                    status="Offline",
                    last_seen="09 June 2026, 13:30:00",
                )
            ],
        )

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["Issue Type"], "Potential Match Manual Review")
        self.assertIn("Offline Last Seen within", rows[0]["Match Evidence"])

    def test_offline_last_seen_beyond_window_does_not_match(self) -> None:
        _, rows = self.run_compare(
            [
                atera_row(
                    device_name="DESKTOP-ABC1",
                    ip_address="",
                    status="Offline",
                    last_seen="2026-06-09T19:55:34Z",
                )
            ],
            [
                bd_row(
                    device_name="DESKTOP-ABC2",
                    ip_address="",
                    status="Offline",
                    last_seen="09 June 2026, 11:30:00",
                )
            ],
        )

        self.assertEqual([row["Issue Type"] for row in rows], ["Missing BD", "Missing Atera"])

    def test_ambiguous_candidates_are_marked_for_manual_review(self) -> None:
        _, rows = self.run_compare(
            [atera_row(device_name="DESKTOP-ABC1", ip_address="10.0.0.1")],
            [
                bd_row(device_name="DESKTOP-ABC2", ip_address="10.0.0.1", row_number="2"),
                bd_row(device_name="DESKTOP-ABC3", ip_address="10.0.0.1", row_number="3"),
            ],
        )

        self.assertEqual(len(rows), 2)
        self.assertEqual(
            {row["Issue Type"] for row in rows},
            {"Ambiguous Potential Match Manual Review"},
        )

    def test_bad_alias_rows_and_bad_source_rows_output_data_quality(self) -> None:
        _, rows = self.run_compare(
            [
                {
                    **atera_row(device_name="", agent_id="A1"),
                    "Company Name": "Acme",
                }
            ],
            [
                {
                    **bd_row(device_name="PC01", row_number="", endpoint_id="bd-bad"),
                    "Company Name": "",
                }
            ],
            company_alias_rows=[{"Atera Company Name": "Acme", "BD Company Name": ""}],
            device_alias_rows=[
                {
                    "Company Name": "Acme",
                    "Raw Device Name": "PC01",
                    "Canonical Device Name": "",
                }
            ],
        )

        self.assertEqual([row["Issue Type"] for row in rows], ["Data Quality Review"] * 4)
        self.assertTrue(any("BD Company Name" in row["Notes"] for row in rows))
        self.assertTrue(any("Canonical Device Name" in row["Notes"] for row in rows))
        self.assertTrue(any("Atera CSV row" in row["Notes"] for row in rows))
        self.assertTrue(any("Bd CSV row" in row["Notes"] for row in rows))
        self.assertTrue(any(row["BD Endpoint IDs"] == "bd-bad" for row in rows))

    def test_non_endpoint_inventory_rows_output_data_quality(self) -> None:
        _, rows = self.run_compare(
            [],
            [
                bd_row(
                    device_name="Acme Company Node",
                    endpoint_id="company-item",
                    company_id="company-1",
                    parent_id="partner-1",
                    network_item_type="1",
                )
            ],
        )

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["Issue Type"], "Data Quality Review")
        self.assertEqual(rows[0]["BD Endpoint IDs"], "company-item")
        self.assertEqual(rows[0]["BD Company IDs"], "company-1")
        self.assertEqual(rows[0]["BD Parent IDs"], "partner-1")
        self.assertEqual(rows[0]["BD Network Item Types"], "1")
        self.assertIn("Network Item Type", rows[0]["Notes"])

    def test_legacy_bd_csv_minimal_columns_are_still_accepted(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            atera_csv = tmp_path / "atera.csv"
            bd_csv = tmp_path / "legacy_bd.csv"
            output = tmp_path / "mismatch.csv"
            duplicates_output = tmp_path / "duplicates.csv"
            write_csv_file(atera_csv, ATERA_CSV_COLUMNS, [atera_row()])
            write_csv_file(
                bd_csv,
                compare.BD_COMPARE_REQUIRED_COLUMNS,
                [
                    {
                        "Device Name": "PC01",
                        "Company Name": "Acme",
                        "IP Address": "10.0.0.1",
                        "Status": "Offline",
                    }
                ],
            )

            count = compare.compare_csvs(atera_csv, bd_csv, output, duplicates_output=duplicates_output)
            _, rows = read_report(output)
            _, duplicate_rows = read_report(duplicates_output)

        self.assertEqual(count, 0)
        self.assertEqual(rows, [])
        self.assertEqual(duplicate_rows, [])

    def test_main_writes_report_and_returns_success(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            atera_csv = tmp_path / "atera.csv"
            bd_csv = tmp_path / "bd.csv"
            output = tmp_path / "mismatch.csv"
            duplicates_output = tmp_path / "duplicates.csv"
            write_csv_file(atera_csv, ATERA_CSV_COLUMNS, [atera_row()])
            write_csv_file(bd_csv, BD_CSV_COLUMNS, [bd_row()])

            stdout = io.StringIO()
            with redirect_stdout(stdout):
                exit_code = compare.main(
                    [
                        "--atera-csv",
                        str(atera_csv),
                        "--bd-csv",
                        str(bd_csv),
                        "--output",
                        str(output),
                        "--duplicates-output",
                        str(duplicates_output),
                    ]
                )

            fieldnames, rows = read_report(output)
            duplicate_fieldnames, duplicate_rows = read_report(duplicates_output)

        self.assertEqual(exit_code, 0)
        self.assertEqual(fieldnames, compare.COMPARE_REPORT_COLUMNS)
        self.assertEqual(rows, [])
        self.assertEqual(duplicate_fieldnames, compare.DUPLICATE_REPORT_COLUMNS)
        self.assertEqual(duplicate_rows, [])
        self.assertIn("Wrote 0 mismatch row", stdout.getvalue())
        self.assertIn("Wrote duplicate entry details", stdout.getvalue())

    def test_parse_args_uses_data_folder_defaults(self) -> None:
        args = compare.parse_args([])

        self.assertEqual(args.atera_csv, Path("data/atera_agents.csv"))
        self.assertEqual(args.bd_csv, Path("data/bd_endpoint_status.csv"))
        self.assertEqual(args.output, Path("data/mismatch.csv"))
        self.assertEqual(args.duplicates_output, Path("data/duplicates.csv"))
        self.assertEqual(args.company_aliases, Path("data/company_aliases.csv"))
        self.assertEqual(args.device_aliases, Path("data/device_aliases.csv"))

    def test_missing_default_alias_files_are_ignored(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            missing_company_aliases = Path(tmp) / "missing_company_aliases.csv"
            missing_device_aliases = Path(tmp) / "missing_device_aliases.csv"

            company_aliases, company_quality_rows = compare.read_company_aliases(missing_company_aliases)
            device_aliases, device_quality_rows = compare.read_device_aliases(
                missing_device_aliases,
                company_aliases,
            )

        self.assertEqual(company_aliases, {})
        self.assertEqual(company_quality_rows, [])
        self.assertEqual(device_aliases, {})
        self.assertEqual(device_quality_rows, [])

    def test_main_returns_nonzero_for_missing_required_headers(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            atera_csv = tmp_path / "atera.csv"
            bd_csv = tmp_path / "bd.csv"
            output = tmp_path / "mismatch.csv"
            write_csv_file(atera_csv, ["Device Name"], [{"Device Name": "PC01"}])
            write_csv_file(bd_csv, BD_CSV_COLUMNS, [bd_row()])

            stderr = io.StringIO()
            with redirect_stderr(stderr):
                exit_code = compare.main(
                    ["--atera-csv", str(atera_csv), "--bd-csv", str(bd_csv), "--output", str(output)]
                )

        self.assertEqual(exit_code, 1)
        self.assertIn("missing required header", stderr.getvalue())


if __name__ == "__main__":
    unittest.main()
