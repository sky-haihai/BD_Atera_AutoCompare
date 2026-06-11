from __future__ import annotations

import csv
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from bd_atera_autocompare import app


def read_rows(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


class AppTests(unittest.TestCase):
    def test_default_settings_use_base_dir_config_and_output_folders(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base_dir = Path(tmp)
            settings = app.default_settings_for_base_dir(base_dir)

        self.assertEqual(settings.env_file, base_dir / ".env")
        self.assertEqual(settings.atera_output, base_dir / "output" / "atera_agents.csv")
        self.assertEqual(settings.bd_output, base_dir / "output" / "bd_endpoint_status.csv")
        self.assertEqual(settings.report_output, base_dir / "output" / "mismatch.csv")
        self.assertEqual(settings.duplicates_output, base_dir / "output" / "duplicates.csv")
        self.assertEqual(settings.company_aliases, base_dir / "config" / "company_aliases.csv")
        self.assertEqual(settings.device_aliases, base_dir / "config" / "device_aliases.csv")
        self.assertEqual(settings.exclude_company, base_dir / "config" / "exclude_company.csv")

    def test_ensure_default_config_csvs_creates_missing_files_with_placeholders(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            settings = app.default_settings_for_base_dir(Path(tmp))

            app.ensure_default_config_csvs(settings)

            self.assertEqual(read_rows(settings.company_aliases), [app.DEFAULT_COMPANY_ALIAS_ROW])
            self.assertEqual(read_rows(settings.device_aliases), [app.DEFAULT_DEVICE_ALIAS_ROW])
            self.assertEqual(read_rows(settings.exclude_company), [app.DEFAULT_EXCLUDE_COMPANY_ROW])

    def test_ensure_default_config_csvs_does_not_overwrite_existing_files(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            settings = app.default_settings_for_base_dir(Path(tmp))
            settings.company_aliases.parent.mkdir(parents=True)
            settings.company_aliases.write_text(
                "Atera Company Name,BD Company Name\nCustom Atera,Custom BD\n",
                encoding="utf-8-sig",
            )

            app.ensure_default_config_csvs(settings)

            self.assertEqual(
                read_rows(settings.company_aliases),
                [{"Atera Company Name": "Custom Atera", "BD Company Name": "Custom BD"}],
            )
            self.assertEqual(read_rows(settings.device_aliases), [app.DEFAULT_DEVICE_ALIAS_ROW])
            self.assertEqual(read_rows(settings.exclude_company), [app.DEFAULT_EXCLUDE_COMPANY_ROW])

    def test_app_base_dir_uses_executable_parent_when_frozen(self) -> None:
        with patch.object(app.sys, "frozen", True, create=True), patch.object(
            app.sys,
            "executable",
            r"C:\Tools\AutoCompare\BD_Atera_AutoCompare.exe",
        ):
            self.assertEqual(app.app_base_dir(), Path(r"C:\Tools\AutoCompare"))


if __name__ == "__main__":
    unittest.main()
