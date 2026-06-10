from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from bd_atera_autocompare import app


class AppTests(unittest.TestCase):
    def test_default_settings_use_base_dir_data_folder(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base_dir = Path(tmp)
            settings = app.default_settings_for_base_dir(base_dir)

        self.assertEqual(settings.env_file, base_dir / ".env")
        self.assertEqual(settings.atera_output, base_dir / "data" / "atera_agents.csv")
        self.assertEqual(settings.bd_output, base_dir / "data" / "bd_endpoint_status.csv")
        self.assertEqual(settings.report_output, base_dir / "data" / "mismatch.csv")
        self.assertEqual(settings.duplicates_output, base_dir / "data" / "duplicates.csv")
        self.assertEqual(settings.company_aliases, base_dir / "data" / "company_aliases.csv")
        self.assertEqual(settings.device_aliases, base_dir / "data" / "device_aliases.csv")

    def test_app_base_dir_uses_executable_parent_when_frozen(self) -> None:
        with patch.object(app.sys, "frozen", True, create=True), patch.object(
            app.sys,
            "executable",
            r"C:\Tools\AutoCompare\BD_Atera_AutoCompare.exe",
        ):
            self.assertEqual(app.app_base_dir(), Path(r"C:\Tools\AutoCompare"))


if __name__ == "__main__":
    unittest.main()
