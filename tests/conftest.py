"""Pytest bootstrap for local package imports.

The parent monorepo has its own ``pyproject.toml``, so pytest can select the
parent directory as ``rootdir`` and drop ``flask_app`` from ``sys.path``.
Ensure this app root is importable for tests that import ``finance_app``.
"""

from __future__ import annotations

import sys
from pathlib import Path

APP_ROOT = Path(__file__).resolve().parents[1]
app_root_str = str(APP_ROOT)
if app_root_str not in sys.path:
    sys.path.insert(0, app_root_str)

TESTS_ROOT = Path(__file__).resolve().parent
tests_root_str = str(TESTS_ROOT)
if tests_root_str not in sys.path:
    sys.path.insert(0, tests_root_str)
