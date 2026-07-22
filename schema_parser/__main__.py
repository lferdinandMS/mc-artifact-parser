from __future__ import annotations

import sys
from pathlib import Path

if __package__ in {None, ""}:
    package_root = Path(__file__).resolve().parent.parent
    if str(package_root) not in sys.path:
        sys.path.insert(0, str(package_root))

from docx_schema.cli import main


if __name__ == "__main__":
    raise SystemExit(main())
