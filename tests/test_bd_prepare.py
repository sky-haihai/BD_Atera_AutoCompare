from __future__ import annotations

import base64
import csv
import io
import json
import os
import sys
import tempfile
import unittest
from contextlib import redirect_stderr
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from bd_atera_autocompare.bd import api as bd_api
from bd_atera_autocompare.bd import mapping as bd_mapping
from bd_atera_autocompare.bd import prepare as bd_prepare
from bd_atera_autocompare.bd import schema as bd_schema


def endpoint_item(
    name: str = "PC01",
    company_id: str = "company-1",
    ip_address: str = "10.0.0.1",
    managed_with_best: object = True,
    endpoint_id: str = "bd-1",
    parent_id: str = "group-1",
) -> dict[str, object]:
    return {
        "id": endpoint_id,
        "name": name,
        "type": 5,
        "parentId": parent_id,
        "companyId": company_id,
        "details": {
            "label": "Front Desk",
            "fqdn": "pc01.acme.local",
            "groupId": parent_id,
            "isManaged": True,
            "machineType": 1,
            "operatingSystemVersion": "Windows 11 Pro",
            "ip": ip_address,
            "macs": ["00:11:22:33:44:55", "00:11:22:33:44:55", "AA:BB:CC:DD:EE:FF"],
            "ssid": "S-1-5-21",
            "managedWithBest": managed_with_best,
            "isContainerHost": False,
            "managedExchangeServer": False,
            "managedRelay": False,
            "securityServer": False,
            "policy": {
                "id": "policy-1",
                "name": "Default",
                "applied": True,
            },
            "modules": {
                "antimalware": True,
                "firewall": False,
            },
            "productOutdated": False,
            "lastSuccessfulScan": {
                "name": "Quick Scan",
                "date": "2026-06-09T19:55:34+00:00",
            },
        },
    }


def company_item(company_id: str = "company-1", name: str = "Acme") -> dict[str, object]:
    return {
        "id": company_id,
        "name": name,
        "type": 1,
        "parentId": "partner-1",
        "companyId": "partner-1",
        "details": {"type": 1},
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


def api_payload(
    items: list[dict[str, object]],
    *,
    page: int = 1,
    pages_count: int = 1,
    has_more_records: bool = False,
) -> dict[str, object]:
    return {
        "jsonrpc": "2.0",
        "id": "test",
        "error": None,
        "result": {
            "total": len(items),
            "page": page,
            "perPage": len(items) or 100,
            "pagesCount": pages_count,
            "hasMoreRecords": has_more_records,
            "items": items,
        },
    }


def custom_groups_payload(items: list[dict[str, object]] | None = None) -> dict[str, object]:
    return {
        "jsonrpc": "2.0",
        "id": "test",
        "error": None,
        "result": {"items": items or []},
    }


class BdPrepareTests(unittest.TestCase):
    def test_map_endpoint_item_uses_network_inventory_fields(self) -> None:
        row = bd_mapping.map_inventory_endpoint_item(
            endpoint_item(name="  PC01  "),
            {"company-1": "Acme"},
        )

        self.assertEqual(row.device_name, "PC01")
        self.assertEqual(row.company_name, "Acme")
        self.assertEqual(row.ip_address, "10.0.0.1")
        self.assertEqual(row.status, "Managed With BEST")
        self.assertEqual(row.mac_addresses, "00:11:22:33:44:55; AA:BB:CC:DD:EE:FF")
        self.assertEqual(row.bd_endpoint_id, "bd-1")
        self.assertEqual(row.bd_company_id, "company-1")
        self.assertEqual(row.parent_id, "group-1")
        self.assertEqual(row.network_item_type, "5")
        self.assertEqual(row.label, "Front Desk")
        self.assertEqual(row.fqdn, "pc01.acme.local")
        self.assertEqual(row.group_id, "group-1")
        self.assertEqual(row.is_managed, "true")
        self.assertEqual(row.managed_with_best, "true")
        self.assertEqual(row.machine_type, "1")
        self.assertEqual(row.operating_system_version, "Windows 11 Pro")
        self.assertEqual(row.policy_id, "policy-1")
        self.assertEqual(row.policy_name, "Default")
        self.assertEqual(row.policy_applied, "true")
        self.assertEqual(row.product_outdated, "false")
        self.assertEqual(row.last_successful_scan_name, "Quick Scan")
        self.assertEqual(row.last_successful_scan_date, "2026-06-09T19:55:34+00:00")
        self.assertEqual(row.modules, "antimalware=true; firewall=false")

    def test_map_endpoint_item_uses_moving_destination_as_company_fallback(self) -> None:
        item = endpoint_item(company_id="missing-company")
        details = item["details"]
        assert isinstance(details, dict)
        details["movingInfo"] = {"state": 1, "destinationCompanyName": "Moved Acme"}
        row = bd_mapping.map_inventory_endpoint_item(
            {
                **item,
            },
            {},
            fallback_company_name="Fallback Acme",
        )

        self.assertEqual(row.company_name, "Moved Acme")
        self.assertEqual(row.destination_company_name, "Moved Acme")
        self.assertEqual(row.moving_state, "1")

    def test_map_endpoint_item_uses_explicit_company_fallback(self) -> None:
        row = bd_mapping.map_inventory_endpoint_item(endpoint_item(company_id="missing-company"), {}, "Fallback Acme")

        self.assertEqual(row.company_name, "Fallback Acme")

    def test_endpoint_status_marks_missing_best(self) -> None:
        row = bd_mapping.map_inventory_endpoint_item(endpoint_item(managed_with_best=False), {"company-1": "Acme"})

        self.assertEqual(row.status, "No BEST")
        self.assertEqual(row.managed_with_best, "false")

    def test_endpoint_status_uses_is_managed_when_best_flag_is_unknown(self) -> None:
        row = bd_mapping.map_inventory_endpoint_item(endpoint_item(managed_with_best=None), {"company-1": "Acme"})

        self.assertEqual(row.status, "Managed")
        self.assertEqual(row.is_managed, "true")
        self.assertEqual(row.managed_with_best, "")

    def test_company_name_map_comes_from_inventory_company_items(self) -> None:
        string_type_company = {**company_item("company-2", "Beta"), "type": "1"}
        string_type_endpoint = {**endpoint_item(endpoint_id="bd-string"), "type": "5"}
        self.assertEqual(
            bd_api.build_company_names_by_id([company_item(), string_type_company, endpoint_item()]),
            {"company-1": "Acme", "company-2": "Beta"},
        )
        self.assertEqual(
            [
                item["id"]
                for item in bd_api.filter_endpoint_items(
                    [company_item(), endpoint_item(), string_type_endpoint]
                )
            ],
            ["bd-1", "bd-string"],
        )

    def test_export_endpoint_filter_keeps_managed_items_when_best_flag_is_unknown(self) -> None:
        items = [
            company_item(),
            endpoint_item(name="WITH-BEST", managed_with_best=True, endpoint_id="with-best"),
            endpoint_item(name="MANAGED-UNKNOWN-BEST", managed_with_best=None, endpoint_id="managed-unknown-best"),
            endpoint_item(name="NO-BEST", managed_with_best=False, endpoint_id="no-best"),
        ]

        self.assertEqual(
            [item["id"] for item in bd_api.filter_export_endpoint_items(items)],
            ["with-best", "managed-unknown-best"],
        )
        self.assertEqual(
            [item["id"] for item in bd_api.filter_export_endpoint_items(items, include_unprotected=True)],
            ["with-best", "managed-unknown-best", "no-best"],
        )

    def test_write_bd_csv_creates_directory_and_preserves_column_order(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "data" / "bd_endpoint_status.csv"
            bd_schema.write_bd_csv(output, [bd_mapping.map_inventory_endpoint_item(endpoint_item(), {"company-1": "Acme"})])

            with output.open("r", encoding="utf-8-sig", newline="") as handle:
                reader = csv.DictReader(handle)
                rows = list(reader)

        self.assertEqual(reader.fieldnames, bd_schema.BD_CSV_COLUMNS)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["Device Name"], "PC01")
        self.assertEqual(rows[0]["MAC Addresses"], "00:11:22:33:44:55; AA:BB:CC:DD:EE:FF")

    def test_write_bd_csv_sorts_by_company_and_device(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "bd_endpoint_status.csv"
            bd_schema.write_bd_csv(
                output,
                [
                    bd_schema.BdNormalizedRow(device_name="PC-Z", company_name="Zoo"),
                    bd_schema.BdNormalizedRow(device_name="PC-C", company_name="Acme"),
                    bd_schema.BdNormalizedRow(device_name="PC-A", company_name="Acme"),
                ],
            )

            with output.open("r", encoding="utf-8-sig", newline="") as handle:
                rows = list(csv.DictReader(handle))

        self.assertEqual(
            [(row["Company Name"], row["Device Name"]) for row in rows],
            [("Acme", "PC-A"), ("Acme", "PC-C"), ("Zoo", "PC-Z")],
        )

    def test_provider_requires_api_key(self) -> None:
        with self.assertRaisesRegex(ValueError, "BD_API_KEY"):
            bd_api.BdApiProvider(api_key="")

    def test_provider_reads_dotenv_without_touching_real_environment(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            env_path = Path(tmp) / ".env"
            env_path.write_text(
                "BD_API_KEY=file-secret\n"
                "BD_API_URL=https://example.test/api/v1.0/jsonrpc/network\n"
                "BD_PARENT_ID=company-1\n"
                "BD_COMPANY_NAME=Acme\n",
                encoding="utf-8",
            )

            provider = bd_api.BdApiProvider.from_environment(
                environ={"BD_API_KEY": "process-secret"},
                env_file=env_path,
            )

        self.assertEqual(provider.api_key, "file-secret")
        self.assertEqual(provider.api_url, "https://example.test/api/v1.0/jsonrpc/network")
        self.assertEqual(provider.parent_id, "company-1")
        self.assertEqual(provider.company_name, "Acme")

    def test_provider_posts_jsonrpc_payload_and_basic_auth_header(self) -> None:
        urlopen = FakeUrlopen([api_payload([company_item(), endpoint_item()]), custom_groups_payload()])
        provider = bd_api.BdApiProvider(
            api_key="secret",
            api_url="https://example.test/api/v1.0/jsonrpc/network",
            timeout=12.0,
            page_size=100,
            parent_id="company-1",
            company_name="Acme",
            urlopen=urlopen,
        )

        rows = provider.get_rows()

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].company_name, "Acme")
        request = urlopen.requests[0]
        body = json.loads(request.data.decode("utf-8"))
        expected_auth = "Basic " + base64.b64encode(b"secret:").decode("ascii")
        self.assertEqual(request.full_url, "https://example.test/api/v1.0/jsonrpc/network")
        self.assertEqual(request.headers["Authorization"], expected_auth)
        self.assertEqual(request.headers["Content-type"], "application/json")
        self.assertEqual(body["method"], "getNetworkInventoryItems")
        self.assertEqual(body["params"]["parentId"], "company-1")
        self.assertEqual(body["params"]["page"], 1)
        self.assertEqual(body["params"]["perPage"], 100)
        self.assertEqual(
            body["params"]["filters"],
            {
                "type": {
                    "companies": True,
                    "computers": True,
                    "virtualMachines": True,
                    "ec2Instances": True,
                },
                "depth": {"allItemsRecursively": True},
            },
        )
        self.assertEqual(
            body["params"]["options"],
            {
                "companies": {"returnAllProducts": True},
                "endpoints": {"returnProductOutdated": True, "includeScanLogs": True},
            },
        )
        deleted_lookup_body = json.loads(urlopen.requests[1].data.decode("utf-8"))
        self.assertEqual(deleted_lookup_body["method"], "getCustomGroupsList")
        self.assertEqual(deleted_lookup_body["params"]["parentId"], "company-1")
        self.assertEqual(urlopen.timeouts, [12.0, 12.0])

    def test_provider_fetches_multiple_pages_until_has_more_records_is_false(self) -> None:
        urlopen = FakeUrlopen(
            [
                api_payload([company_item(), endpoint_item(name="PC01")], page=1, pages_count=2, has_more_records=True),
                api_payload([endpoint_item(name="PC02")], page=2, pages_count=2, has_more_records=False),
                custom_groups_payload(),
                custom_groups_payload(),
            ]
        )
        provider = bd_api.BdApiProvider(
            api_key="secret",
            page_size=1,
            company_name="Acme",
            urlopen=urlopen,
        )

        rows = provider.get_rows()

        self.assertEqual([row.device_name for row in rows], ["PC01", "PC02"])

    def test_provider_includes_unprotected_inventory_for_complete_status_csv(self) -> None:
        urlopen = FakeUrlopen(
            [
                api_payload(
                    [
                        company_item(),
                        endpoint_item(name="WITH-BEST", managed_with_best=True, endpoint_id="with-best"),
                        endpoint_item(
                            name="MANAGED-UNKNOWN-BEST",
                            managed_with_best=None,
                            endpoint_id="managed-unknown-best",
                        ),
                        endpoint_item(name="NO-BEST", managed_with_best=False, endpoint_id="no-best"),
                    ]
                ),
                custom_groups_payload(),
                custom_groups_payload(),
            ]
        )
        provider = bd_api.BdApiProvider(api_key="secret", urlopen=urlopen)

        rows = provider.get_rows()

        self.assertEqual([row.device_name for row in rows], ["WITH-BEST", "MANAGED-UNKNOWN-BEST", "NO-BEST"])
        self.assertEqual(rows[1].status, "Managed")
        self.assertEqual(rows[2].status, "No BEST")

    def test_provider_include_unprotected_flag_is_kept_for_compatibility(self) -> None:
        urlopen = FakeUrlopen(
            [
                api_payload(
                    [
                        company_item(),
                        endpoint_item(name="WITH-BEST", managed_with_best=True, endpoint_id="with-best"),
                        endpoint_item(name="NO-BEST", managed_with_best=False, endpoint_id="no-best"),
                    ]
                ),
                custom_groups_payload(),
                custom_groups_payload(),
            ]
        )
        provider = bd_api.BdApiProvider(api_key="secret", include_unprotected=True, urlopen=urlopen)

        rows = provider.get_rows()

        self.assertEqual([row.device_name for row in rows], ["WITH-BEST", "NO-BEST"])

    def test_provider_marks_deleted_folder_items(self) -> None:
        urlopen = FakeUrlopen(
            [
                api_payload([company_item(), endpoint_item(name="LIVE", endpoint_id="live")]),
                custom_groups_payload([{"id": "deleted-group", "name": "Deleted"}]),
                api_payload(
                    [
                        endpoint_item(
                            name="DELETED",
                            endpoint_id="deleted",
                            parent_id="deleted-group",
                        )
                    ]
                ),
            ]
        )
        provider = bd_api.BdApiProvider(
            api_key="secret",
            parent_id="company-1",
            company_name="Acme",
            urlopen=urlopen,
        )

        rows = provider.get_rows()

        self.assertEqual([row.device_name for row in rows], ["LIVE", "DELETED"])
        self.assertEqual(rows[0].is_in_deleted_folder, "")
        self.assertEqual(rows[1].is_in_deleted_folder, "true")
        custom_groups_body = json.loads(urlopen.requests[1].data.decode("utf-8"))
        deleted_inventory_body = json.loads(urlopen.requests[2].data.decode("utf-8"))
        self.assertEqual(custom_groups_body["method"], "getCustomGroupsList")
        self.assertEqual(custom_groups_body["params"]["parentId"], "company-1")
        self.assertEqual(deleted_inventory_body["method"], "getNetworkInventoryItems")
        self.assertEqual(deleted_inventory_body["params"]["parentId"], "deleted-group")
        self.assertEqual(deleted_inventory_body["params"]["perPage"], 100)
        self.assertEqual(
            deleted_inventory_body["params"]["filters"],
            {
                "type": {
                    "computers": True,
                    "virtualMachines": True,
                    "ec2Instances": True,
                },
                "depth": {"allItemsRecursively": True},
            },
        )

    def test_provider_checks_each_company_deleted_folder_without_configured_parent(self) -> None:
        urlopen = FakeUrlopen(
            [
                api_payload([company_item(), endpoint_item(name="LIVE", endpoint_id="live")]),
                custom_groups_payload(),
                custom_groups_payload([{"id": "company-deleted-group", "name": "Deleted"}]),
                api_payload(
                    [
                        endpoint_item(
                            name="COMPANY-DELETED",
                            endpoint_id="company-deleted",
                            parent_id="company-deleted-group",
                        )
                    ]
                ),
            ]
        )
        provider = bd_api.BdApiProvider(
            api_key="secret",
            company_name="Acme",
            urlopen=urlopen,
        )

        rows = provider.get_rows()

        self.assertEqual([row.device_name for row in rows], ["LIVE", "COMPANY-DELETED"])
        self.assertEqual(rows[0].is_in_deleted_folder, "")
        self.assertEqual(rows[1].is_in_deleted_folder, "true")
        root_groups_body = json.loads(urlopen.requests[1].data.decode("utf-8"))
        company_groups_body = json.loads(urlopen.requests[2].data.decode("utf-8"))
        deleted_inventory_body = json.loads(urlopen.requests[3].data.decode("utf-8"))
        self.assertEqual(root_groups_body["method"], "getCustomGroupsList")
        self.assertIsNone(root_groups_body["params"]["parentId"])
        self.assertEqual(company_groups_body["method"], "getCustomGroupsList")
        self.assertEqual(company_groups_body["params"]["parentId"], "company-1")
        self.assertEqual(deleted_inventory_body["params"]["parentId"], "company-deleted-group")

    def test_extract_result_raises_for_jsonrpc_error(self) -> None:
        with self.assertRaisesRegex(RuntimeError, "Authorization error"):
            bd_api.extract_result(
                {
                    "jsonrpc": "2.0",
                    "id": "test",
                    "error": {"code": -32001, "message": "Authorization error"},
                }
            )

    def test_prepare_bd_csv_writes_provider_rows(self) -> None:
        class FakeProvider:
            def get_rows(self) -> list[bd_schema.BdNormalizedRow]:
                return [bd_schema.BdNormalizedRow(device_name="PC01", company_name="Acme", bd_endpoint_id="bd-1")]

        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "bd.csv"
            count = bd_prepare.prepare_bd_csv(FakeProvider(), output)

        self.assertEqual(count, 1)

    def test_parse_args_uses_api_defaults(self) -> None:
        args = bd_prepare.parse_args([])

        self.assertEqual(args.output, bd_prepare.DEFAULT_BD_OUTPUT_PATH)
        self.assertEqual(args.env_file, Path(".env"))
        self.assertEqual(args.page_size, bd_prepare.DEFAULT_PAGE_SIZE)
        self.assertFalse(args.no_recursive)
        self.assertFalse(args.include_unprotected)

    def test_main_returns_nonzero_when_environment_is_missing_api_key(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            missing_env = Path(tmp) / "missing.env"
            stderr = io.StringIO()
            with patch.dict(os.environ, {}, clear=True), redirect_stderr(stderr):
                exit_code = bd_prepare.main(["--env-file", str(missing_env)])

        self.assertEqual(exit_code, 1)
        self.assertIn("BD_API_KEY", stderr.getvalue())


if __name__ == "__main__":
    unittest.main()
