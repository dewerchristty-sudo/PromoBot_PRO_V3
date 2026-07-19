"""Aponta o Playwright empacotado para o Chromium portatil."""

import os
import sys
from pathlib import Path


if getattr(sys, "frozen", False):
    bundle_root = Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent))
    os.environ["PLAYWRIGHT_BROWSERS_PATH"] = str(bundle_root / "ms-playwright")
