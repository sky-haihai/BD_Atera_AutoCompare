from __future__ import annotations

import csv
import tempfile
import unittest
from pathlib import Path

import bd_atera_compare as tool


def atera_agent(
    name: str,
    company: str = "Acme",
    ip: str = "10.0.0.1",
    online: bool = True,
    last_seen: str = "2026-06-04 10:00",
    agent_id: str = "A1",
) -> dict[str, object]:
    return {
        "MachineName": name,
        "CustomerName": company,
        "IPAddress": ip,
        "Online": online,
        "LastSeen": last_seen,
        "AgentID": agent_id,
        "MachineID": f"M-{agent_id}",
        "DeviceGUID": f"G-{agent_id}",
    }


def bd_row(
    name: str,
    company: str = "Acme",
    ip: str = "10.0.0.1",
    status: str = "Online",
    last_seen: str = "2026-06-04 10:00",
) -> dict[str, str]:
    return {
        "Device Name": name,
        "Company Name": company,
        "IP Address": ip,
        "Status": status,
        "Last Seen": last_seen,
    }


class CompareTests(unittest.TestCase):
    def compare(self, atera_rows, bd_rows, aliases=None):
        alias_map = aliases or {}
        atera_records, atera_dq = tool.build_atera_records(atera_rows, alias_map)
        bd_records, bd_dq = tool.build_bd_records(
            [{**row, "_csv_row_number": str(index)} for index, row in enumerate(bd_rows, start=2)],
            alias_map,
        )
        return tool.compare_records(atera_records, bd_records, atera_dq + bd_dq)

    def test_exact_match_is_omitted(self):
        rows = self.compare([atera_agent("PC01")], [bd_row("PC01")])
        self.assertEqual(rows, [])

    def test_case_and_space_normalization(self):
        rows = self.compare([atera_agent(" pc01 ")], [bd_row("PC01")])
        self.assertEqual(rows, [])

    def test_alias_maps_annotated_name_and_is_company_scoped(self):
        aliases = {
            (tool.normalize_key("Acme"), tool.normalize_key("DESKTOP-J6QIIND(Datatrasfer to Alison)")): "DESKTOP-J6QIIND"
        }
        rows = self.compare(
            [
                atera_agent("DESKTOP-J6QIIND(Datatrasfer to Alison)", company="Acme"),
                atera_agent("DESKTOP-J6QIIND(Datatrasfer to Alison)", company="OtherCo"),
            ],
            [
                bd_row("DESKTOP-J6QIIND", company="Acme"),
                bd_row("DESKTOP-J6QIIND", company="OtherCo"),
            ],
            aliases=aliases,
        )

        self.assertEqual(len(rows), 2)
        self.assertEqual({row["Company Name"] for row in rows}, {"OtherCo"})
        self.assertEqual({row["Issue Type"] for row in rows}, {"Missing BD", "Missing Atera"})

    def test_duplicate_detection_happens_after_aliasing(self):
        aliases = {
            (tool.normalize_key("Acme"), tool.normalize_key("PC01(old)")): "PC01",
        }
        rows = self.compare(
            [atera_agent("PC01"), atera_agent("PC01(old)", agent_id="A2")],
            [bd_row("PC01")],
            aliases=aliases,
        )

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["Issue Type"], "Duplicate Manual Review")
        self.assertEqual(rows[0]["Atera Count"], "2")

    def test_missing_atera_and_missing_bd_output(self):
        rows = self.compare([atera_agent("AteraOnly")], [bd_row("BDOnly")])
        issue_types = {row["Issue Type"] for row in rows}

        self.assertEqual(issue_types, {"Missing BD", "Missing Atera"})

    def test_ipv4_and_similar_name_creates_potential_match(self):
        rows = self.compare(
            [atera_agent("DESKTOP-ABC123", ip="10.1.2.3")],
            [bd_row("DESKTOP-ABC124", ip="10.1.2.3")],
        )

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["Issue Type"], "Potential Match Manual Review")
        self.assertIn("IPv4 match", rows[0]["Match Evidence"])

    def test_ipv6_is_ignored(self):
        rows = self.compare(
            [atera_agent("DESKTOP-ABC123", ip="fe80::1")],
            [bd_row("DESKTOP-ABC124", ip="fe80::1")],
        )

        self.assertEqual({row["Issue Type"] for row in rows}, {"Missing BD", "Missing Atera"})

    def test_offline_last_seen_within_60_minutes_creates_potential_match(self):
        rows = self.compare(
            [atera_agent("DESKTOP-ABC123", ip="", online=False, last_seen="2026-06-04 10:00")],
            [bd_row("DESKTOP-ABC124", ip="", status="Offline", last_seen="2026-06-04 10:45")],
        )

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["Issue Type"], "Potential Match Manual Review")
        self.assertIn("last seen", rows[0]["Match Evidence"])

    def test_last_seen_beyond_60_minutes_does_not_match(self):
        rows = self.compare(
            [atera_agent("DESKTOP-ABC123", ip="", online=False, last_seen="2026-06-04 10:00")],
            [bd_row("DESKTOP-ABC124", ip="", status="Offline", last_seen="2026-06-04 11:30")],
        )

        self.assertEqual({row["Issue Type"] for row in rows}, {"Missing BD", "Missing Atera"})

    def test_ambiguous_candidates_are_marked(self):
        rows = self.compare(
            [atera_agent("DESKTOP-ABC123", ip="10.1.2.3")],
            [
                bd_row("DESKTOP-ABC124", ip="10.1.2.3"),
                bd_row("DESKTOP-ABC125", ip="10.1.2.3"),
            ],
        )

        self.assertTrue(rows)
        self.assertEqual({row["Issue Type"] for row in rows}, {"Ambiguous Potential Match Manual Review"})


class CsvTests(unittest.TestCase):
    def test_missing_required_bd_headers_fail_clearly(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "bad_bd.csv"
            with path.open("w", encoding="utf-8", newline="") as handle:
                writer = csv.DictWriter(handle, fieldnames=["Device Name", "Company Name"])
                writer.writeheader()
                writer.writerow({"Device Name": "PC01", "Company Name": "Acme"})

            with self.assertRaisesRegex(ValueError, "missing required header"):
                tool.read_csv_dicts(path, tool.BD_REQUIRED_HEADERS)


if __name__ == "__main__":
    unittest.main()
