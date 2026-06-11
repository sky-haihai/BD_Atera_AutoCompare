from __future__ import annotations

import csv
import io
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from bd_atera_autocompare import cli
from bd_atera_autocompare import pipeline
from bd_atera_autocompare.atera.schema import AteraNormalizedRow
from bd_atera_autocompare.bd.schema import BdNormalizedRow


class FakeAteraProvider:
    def get_rows(self) -> list[AteraNormalizedRow]:
        return [
            AteraNormalizedRow(
                device_name="PC01",
                company_name="Acme",
                ip_address="10.0.0.1",
                mac_addresses="00:11:22:33:44:55",
                status="Online",
            )
        ]


class FakeBdProvider:
    def get_rows(self) -> list[BdNormalizedRow]:
        return [
            BdNormalizedRow(
                device_name="PC01",
                company_name="Acme",
                ip_address="10.0.0.1",
                status="Managed With BEST",
                mac_addresses="00:11:22:33:44:55",
                managed_with_best="true",
                network_item_type="5",
            )
        ]


def read_rows(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


class PipelineCliTests(unittest.TestCase):
    def test_parse_args_uses_full_pipeline_defaults(self) -> None:
        args = cli.parse_args([])

        self.assertEqual(args.atera_output, Path("output/atera_agents.csv"))
        self.assertEqual(args.bd_output, Path("output/bd_endpoint_status.csv"))
        self.assertEqual(args.report_output, Path("output/mismatch.csv"))
        self.assertEqual(args.duplicates_output, Path("output/duplicates.csv"))
        self.assertEqual(args.company_aliases, Path("config/company_aliases.csv"))
        self.assertEqual(args.device_aliases, Path("config/device_aliases.csv"))
        self.assertEqual(args.exclude_company, Path("config/exclude_company.csv"))

    def test_main_runs_atera_pull_bd_pull_and_compare_once(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            env_file = tmp_path / ".env"
            atera_output = tmp_path / "data" / "atera.csv"
            bd_output = tmp_path / "data" / "bd.csv"
            report_output = tmp_path / "reports" / "mismatch.csv"
            duplicates_output = tmp_path / "reports" / "duplicates.csv"
            missing_company_aliases = tmp_path / "company_aliases.csv"
            missing_device_aliases = tmp_path / "device_aliases.csv"
            missing_exclude_company = tmp_path / "exclude_company.csv"

            stdout = io.StringIO()
            with (
                patch.object(
                    pipeline.AteraApiProvider,
                    "from_environment",
                    return_value=FakeAteraProvider(),
                ) as atera_env,
                patch.object(
                    pipeline.BdApiProvider,
                    "from_environment",
                    return_value=FakeBdProvider(),
                ) as bd_env,
                redirect_stdout(stdout),
            ):
                exit_code = cli.main(
                    [
                        "--env-file",
                        str(env_file),
                        "--http-timeout",
                        "12",
                        "--atera-output",
                        str(atera_output),
                        "--atera-page-size",
                        "50",
                        "--bd-output",
                        str(bd_output),
                        "--bd-api-url",
                        "https://example.test/jsonrpc/network",
                        "--bd-page-size",
                        "75",
                        "--bd-parent-id",
                        "company-1",
                        "--bd-company-name",
                        "Acme",
                        "--bd-no-recursive",
                        "--bd-no-product-outdated",
                        "--bd-no-scan-logs",
                        "--bd-include-unprotected",
                        "--report-output",
                        str(report_output),
                        "--duplicates-output",
                        str(duplicates_output),
                        "--company-aliases",
                        str(missing_company_aliases),
                        "--device-aliases",
                        str(missing_device_aliases),
                        "--exclude-company",
                        str(missing_exclude_company),
                    ]
                )

            self.assertEqual(exit_code, 0)
            self.assertEqual(read_rows(atera_output)[0]["Device Name"], "PC01")
            self.assertEqual(read_rows(bd_output)[0]["Device Name"], "PC01")
            self.assertEqual(read_rows(report_output), [])
            self.assertEqual(read_rows(duplicates_output), [])
            atera_env.assert_called_once_with(env_file=env_file, timeout=12.0, page_size=50)
            bd_env.assert_called_once_with(
                env_file=env_file,
                timeout=12.0,
                page_size=75,
                recursive=False,
                return_product_outdated=False,
                include_scan_logs=False,
                include_unprotected=True,
                api_url="https://example.test/jsonrpc/network",
                parent_id="company-1",
                company_name="Acme",
            )
            self.assertIn("Wrote 1 Atera row(s)", stdout.getvalue())
            self.assertIn("Wrote 1 BD row(s)", stdout.getvalue())
            self.assertIn("Wrote 0 mismatch row(s)", stdout.getvalue())


if __name__ == "__main__":
    unittest.main()
