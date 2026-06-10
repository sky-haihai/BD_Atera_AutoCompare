from __future__ import annotations

import sys
from pathlib import Path

SOURCE_DIR = Path(__file__).resolve().parent / "src"
if SOURCE_DIR.exists():
    sys.path.insert(0, str(SOURCE_DIR))

from bd_atera_autocompare.app import main


if __name__ == "__main__":
    raise SystemExit(main())
