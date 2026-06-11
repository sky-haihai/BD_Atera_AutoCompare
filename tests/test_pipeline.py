from __future__ import annotations

import csv
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

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


class PipelineTests(unittest.TestCase):
    def test_run_pipeline_pulls_both_sources_and_compares_outputs(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            settings = pipeline.PipelineSettings(
                env_file=tmp_path / ".env",
                http_timeout=12.0,
                atera_output=tmp_path / "atera.csv",
                atera_page_size=50,
                bd_output=tmp_path / "bd.csv",
                bd_api_url="https://example.test/jsonrpc/network",
                bd_page_size=75,
                bd_parent_id="company-1",
                bd_company_name="Acme",
                bd_recursive=False,
                bd_return_product_outdated=False,
                bd_include_scan_logs=False,
                bd_include_unprotected=True,
                report_output=tmp_path / "mismatch.csv",
                duplicates_output=tmp_path / "duplicates.csv",
                company_aliases=tmp_path / "company_aliases.csv",
                device_aliases=tmp_path / "device_aliases.csv",
                exclude_company=tmp_path / "exclude_company.csv",
            )
            messages: list[str] = []

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
            ):
                result = pipeline.run_pipeline(settings, status=messages.append)

            self.assertEqual(result.atera_rows, 1)
            self.assertEqual(result.bd_rows, 1)
            self.assertEqual(result.mismatch_rows, 0)
            self.assertEqual(read_rows(settings.atera_output)[0]["Device Name"], "PC01")
            self.assertEqual(read_rows(settings.bd_output)[0]["Device Name"], "PC01")
            self.assertEqual(read_rows(settings.report_output), [])
            self.assertEqual(read_rows(settings.duplicates_output), [])
            atera_env.assert_called_once_with(env_file=settings.env_file, timeout=12.0, page_size=50)
            bd_env.assert_called_once_with(
                env_file=settings.env_file,
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
        self.assertTrue(any("Pulling Atera" in message for message in messages))
        self.assertTrue(any("Comparing" in message for message in messages))


if __name__ == "__main__":
    unittest.main()
