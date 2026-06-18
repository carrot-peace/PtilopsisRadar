# coding=utf-8
"""Version parsing helpers for PtilopsisRadar product versions."""

from __future__ import annotations

import re
from typing import Tuple


_VERSION_RE = re.compile(r"^\s*v?(\d+)\.(\d+)\.(\d+)(?:[-+][A-Za-z0-9.-]+)?\s*$")


def parse_version_tuple(version_str: str) -> Tuple[int, int, int]:
    """Parse ``x.y.z`` or ``x.y.z-suffix`` into a comparable numeric tuple."""
    if not isinstance(version_str, str):
        return 0, 0, 0
    match = _VERSION_RE.match(version_str)
    if not match:
        return 0, 0, 0
    return int(match.group(1)), int(match.group(2)), int(match.group(3))


def compare_version_tuple(local: str, remote: str) -> int:
    """Return -1, 0, or 1 comparing version numeric tuples."""
    local_tuple = parse_version_tuple(local)
    remote_tuple = parse_version_tuple(remote)
    if local_tuple < remote_tuple:
        return -1
    if local_tuple > remote_tuple:
        return 1
    return 0
