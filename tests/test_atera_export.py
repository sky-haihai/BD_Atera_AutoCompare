from __future__ import annotations

import csv
import io
import json
import os
import sys
import tempfile
import unittest
import urllib.error
from contextlib import redirect_stderr
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from bd_atera_autocompare import env_file
from bd_atera_autocompare.atera import api as atera_api
from bd_atera_autocompare.atera import export as atera_export
from bd_atera_autocompare.atera import mapping as atera_mapping
from bd_atera_autocompare.atera import schema as atera_schema


def raw_agent(
    machine_name: str = "PC01",
    customer_name: str = "Acme",
    ip_address: str = "10.0.0.1",
    online: object = True,
    last_seen: str = "2026-06-04T10:00:00Z",
    agent_id: str = "A1",
) -> dict[str, object]:
    return {
        "MachineName": machine_name,
        "CustomerName": customer_name,
        "IpAddresses": [ip_address],
        "ReportedFromIP": "203.0.113.10",
        "MacAddresses": ["00:11:22:33:44:55"],
        "VendorSerialNumber": "SN-123",
        "Online": online,
        "LastSeen": last_seen,
        "AgentID": agent_id,
        "MachineID": f"M-{agent_id}",
        "DeviceGuid": f"G-{agent_id}",
    }


class FakeResponse:
    def __init__(self, payload: object) -> None:
        self.payload = payload

    def __enter__(self) -> FakeResponse:
        return self

    def __exit__(self, *args: object) -> None:
        return None

    def read(self) -> bytes:
        return json.dumps(self.payload).encode("utf-8")


class FakeUrlopen:
    def __init__(self, payloads: list[object]) -> None:
        self.payloads = payloads
        self.requests: list[object] = []
        self.timeouts: list[float] = []

    def __call__(self, request: object, timeout: float) -> FakeResponse:
        self.requests.append(request)
        self.timeouts.append(timeout)
        payload = self.payloads.pop(0)
        if isinstance(payload, Exception):
            raise payload
        return FakeResponse(payload)


class AteraExportTests(unittest.TestCase):
    def test_map_raw_agent_trims_only_contract_fields_and_maps_columns(self) -> None:
        row = atera_mapping.map_raw_agent(
            raw_agent(
                machine_name="  DESKTOP-J6QIIND(Datatrasfer to Alison)  ",
                customer_name="  Acme  ",
                online=False,
            )
        )

        self.assertEqual(row.device_name, "DESKTOP-J6QIIND(Datatrasfer to Alison)")
        self.assertEqual(row.company_name, "Acme")
        self.assertEqual(row.status, "Offline")
        self.assertEqual(
            row.to_csv_row(),
            {
                "Device Name": "DESKTOP-J6QIIND(Datatrasfer to Alison)",
                "Company Name": "Acme",
                "IP Address": "10.0.0.1",
                "Reported From IP": "203.0.113.10",
                "MAC Addresses": "00:11:22:33:44:55",
                "Serial Number": "SN-123",
                "Status": "Offline",
                "Last Seen": "2026-06-04T10:00:00Z",
                "Atera Agent ID": "A1",
                "Atera Machine ID": "M-A1",
                "Atera Device GUID": "G-A1",
            },
        )

    def test_convert_online_status_handles_booleans_strings_and_unknowns(self) -> None:
        self.assertEqual(atera_mapping.convert_online_status(True), "Online")
        self.assertEqual(atera_mapping.convert_online_status(False), "Offline")
        self.assertEqual(atera_mapping.convert_online_status("true"), "Online")
        self.assertEqual(atera_mapping.convert_online_status("0"), "Offline")
        self.assertEqual(atera_mapping.convert_online_status("Sleeping"), "Sleeping")

    def test_map_raw_agent_joins_multiple_ips_and_mac_addresses(self) -> None:
        row = atera_mapping.map_raw_agent(
            {
                **raw_agent(),
                "IpAddresses": ["10.0.0.1", "", "10.0.0.2", "10.0.0.1"],
                "MacAddresses": ["AA:BB:CC:DD:EE:FF", "aa:bb:cc:dd:ee:ff", "11:22:33:44:55:66"],
            }
        )

        self.assertEqual(row.ip_address, "10.0.0.1; 10.0.0.2")
        self.assertEqual(row.mac_addresses, "AA:BB:CC:DD:EE:FF; 11:22:33:44:55:66")

    def test_map_raw_agent_keeps_legacy_ip_and_device_guid_fallbacks(self) -> None:
        row = atera_mapping.map_raw_agent(
            {
                **raw_agent(),
                "IpAddresses": [],
                "IPAddress": "10.0.0.9",
                "DeviceGuid": "",
                "DeviceGUID": "legacy-guid",
            }
        )

        self.assertEqual(row.ip_address, "10.0.0.9")
        self.assertEqual(row.atera_device_guid, "legacy-guid")

    def test_write_atera_csv_creates_directory_and_preserves_column_order(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "data" / "atera_agents.csv"
            atera_schema.write_atera_csv(output, [atera_mapping.map_raw_agent(raw_agent())])

            with output.open("r", encoding="utf-8-sig", newline="") as handle:
                reader = csv.DictReader(handle)
                rows = list(reader)

            self.assertEqual(reader.fieldnames, atera_schema.ATERA_CSV_COLUMNS)
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]["Device Name"], "PC01")

    def test_validate_normalized_rows_requires_device_and_company(self) -> None:
        rows = [atera_schema.AteraNormalizedRow(device_name="", company_name="Acme")]

        with self.assertRaisesRegex(ValueError, "Device Name"):
            atera_schema.validate_normalized_rows(rows)

    def test_provider_requires_api_key(self) -> None:
        with self.assertRaisesRegex(ValueError, "ATERA_API_KEY"):
            atera_api.AteraApiProvider(api_key="")

    def test_env_file_parser_ignores_comments_and_unquotes_values(self) -> None:
        self.assertIsNone(env_file.parse_env_line("# comment"))
        self.assertIsNone(env_file.parse_env_line(""))
        self.assertEqual(env_file.parse_env_line('ATERA_API_KEY="secret"'), ("ATERA_API_KEY", "secret"))
        self.assertEqual(env_file.parse_env_line("ATERA_BASE_URL=https://example.test"), ("ATERA_BASE_URL", "https://example.test"))

    def test_provider_prefers_dotenv_values_over_process_environment(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            env_path = Path(tmp) / ".env"
            env_path.write_text(
                "ATERA_API_KEY=file-secret\nATERA_BASE_URL=https://file.example/api/v3\n",
                encoding="utf-8",
            )

            provider = atera_api.AteraApiProvider.from_environment(
                environ={
                    "ATERA_API_KEY": "process-secret",
                    "ATERA_BASE_URL": "https://process.example/api/v3",
                },
                env_file=env_path,
            )

        self.assertEqual(provider.api_key, "file-secret")
        self.assertEqual(provider.base_url, "https://file.example/api/v3")

    def test_provider_reads_user_agent_from_dotenv(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            env_path = Path(tmp) / ".env"
            env_path.write_text(
                "ATERA_API_KEY=file-secret\nATERA_USER_AGENT=custom-agent/1.0\n",
                encoding="utf-8",
            )

            provider = atera_api.AteraApiProvider.from_environment(env_file=env_path)

        self.assertEqual(provider.user_agent, "custom-agent/1.0")

    def test_provider_fetches_items_payload_and_sets_headers(self) -> None:
        urlopen = FakeUrlopen([{"items": [raw_agent()], "totalPages": 1}])
        provider = atera_api.AteraApiProvider(
            api_key="secret",
            base_url="https://example.test/api/v3/",
            timeout=12.0,
            urlopen=urlopen,
        )

        agents = provider.fetch_raw_agents()

        self.assertEqual(len(agents), 1)
        request = urlopen.requests[0]
        self.assertIn("/agents?page=1&itemsInPage=100", request.full_url)
        self.assertEqual(request.headers["X-api-key"], "secret")
        self.assertEqual(request.headers["Accept"], "application/json")
        self.assertEqual(request.headers["User-agent"], atera_api.DEFAULT_ATERA_USER_AGENT)
        self.assertEqual(urlopen.timeouts, [12.0])

    def test_provider_fetches_data_payload_until_total_count(self) -> None:
        urlopen = FakeUrlopen(
            [
                {"data": [raw_agent("PC01")], "totalCount": 2},
                {"data": [raw_agent("PC02")], "totalCount": 2},
            ]
        )
        provider = atera_api.AteraApiProvider(
            api_key="secret",
            page_size=1,
            urlopen=urlopen,
        )

        rows = provider.get_rows()

        self.assertEqual([row.device_name for row in rows], ["PC01", "PC02"])

    def test_provider_retries_transient_http_errors(self) -> None:
        transient = urllib.error.HTTPError(
            "https://example.test/api/v3/agents",
            500,
            "Server Error",
            hdrs=None,
            fp=io.BytesIO(b"temporary"),
        )
        urlopen = FakeUrlopen([transient, {"agents": [raw_agent()], "totalPages": 1}])
        sleeps: list[float] = []
        provider = atera_api.AteraApiProvider(
            api_key="secret",
            urlopen=urlopen,
            sleep=sleeps.append,
        )

        agents = provider.fetch_raw_agents()

        self.assertEqual(len(agents), 1)
        self.assertEqual(sleeps, [1])

    def test_extract_agent_items_fails_when_payload_shape_is_unknown(self) -> None:
        with self.assertRaisesRegex(ValueError, "agents list"):
            atera_api.extract_agent_items({"unexpected": "shape"})

    def test_parse_args_uses_fixed_default_output_path(self) -> None:
        args = atera_export.parse_args([])

        self.assertEqual(args.output, atera_export.DEFAULT_ATERA_OUTPUT_PATH)

    def test_main_returns_nonzero_when_environment_is_missing_api_key(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            missing_env = Path(tmp) / "missing.env"
            stderr = io.StringIO()
            with patch.dict(os.environ, {}, clear=True), redirect_stderr(stderr):
                exit_code = atera_export.main(["--env-file", str(missing_env)])

        self.assertEqual(exit_code, 1)
        self.assertIn("ATERA_API_KEY", stderr.getvalue())


if __name__ == "__main__":
    unittest.main()
