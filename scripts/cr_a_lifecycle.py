#!/usr/bin/env python3
# coding=utf-8
"""Compatibility wrapper for :mod:`trendradar.cr.lifecycle_runner`.

Existing operator commands may continue to run
``python scripts/cr_a_lifecycle.py``.  New integrations should import or run
the installable package module directly.
"""

import sys
from pathlib import Path

# Direct script execution puts ``scripts/`` (not the repository root) on
# sys.path.  Preserve the historical checkout command without affecting the
# installed runtime, which imports the package module normally.
if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from trendradar.cr.lifecycle_runner import (
    CRLifecycleRunResult,
    DEFAULT_REPORT_PATH,
    DEFAULT_STATE_PATH,
    REPORT_SCHEMA_VERSION,
    build_ttl_for_level,
    main,
    run_lifecycle,
)

__all__ = [
    "CRLifecycleRunResult",
    "DEFAULT_REPORT_PATH",
    "DEFAULT_STATE_PATH",
    "REPORT_SCHEMA_VERSION",
    "build_ttl_for_level",
    "main",
    "run_lifecycle",
]


if __name__ == "__main__":
    raise SystemExit(main())
