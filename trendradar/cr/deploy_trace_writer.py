# coding=utf-8
"""
CR-A deploy trace writer (PR-CR-A6b) v0.1.

Wires the standalone CR deploy_trace reader into deploy_trace JSON output
lifecycle.  Writes deploy trace observations to latest + archive artifact
paths.

This module is read-only with respect to CR artifacts and CR state.  It does
not send Telegram, does not mutate dispatch state, and does not regenerate
CR plan/receipt artifacts.

Design reference: PR-CR-A6b.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from trendradar.cr.deploy_trace_reader import read_cr_deploy_trace


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

DEPLOY_TRACE_SCHEMA_VERSION = "deploy-trace-v1"
DEFAULT_DEPLOY_TRACE_ROOT = "output/meta/deploy_trace"
DEFAULT_LATEST_FILENAME = "latest.json"
DEFAULT_ARCHIVE_DIRNAME = "archive"


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class DeployTraceConfig:
    """Configuration for deploy trace output paths."""

    root_dir: Path | str = DEFAULT_DEPLOY_TRACE_ROOT
    latest_filename: str = DEFAULT_LATEST_FILENAME
    archive_dirname: str = DEFAULT_ARCHIVE_DIRNAME


# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class DeployTracePaths:
    """Resolved deploy trace artifact paths."""

    latest_path: Path
    archive_path: Path


def _safe_slug(label: str) -> str:
    """Sanitize a run label into a filesystem-safe slug."""
    import re
    import unicodedata

    normalized = unicodedata.normalize("NFKC", label).strip()
    out: list[str] = []
    for ch in normalized:
        if ch in ("/", "\\", ":", ";", "|", " "):
            out.append("-")
        elif ch.isalnum() or ch in ("_", "-", "."):
            out.append(ch)
        else:
            out.append("-")
    slug = re.sub(r"-+", "-", "".join(out)).strip("-")
    return slug or "run"


def resolve_deploy_trace_paths(
    *,
    run_label: str,
    config: DeployTraceConfig | None = None,
) -> DeployTracePaths:
    """Resolve deploy trace artifact paths for *run_label*."""
    if config is None:
        config = DeployTraceConfig()

    root = Path(config.root_dir)
    safe = _safe_slug(run_label)
    archive_dir = root / config.archive_dirname

    return DeployTracePaths(
        latest_path=root / config.latest_filename,
        archive_path=archive_dir / f"{safe}.json",
    )


# ---------------------------------------------------------------------------
# Writer
# ---------------------------------------------------------------------------


def _write_json(path: Path, data: dict, encoding: str = "utf-8") -> Path:
    """Write JSON to path, creating parent directories."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(data, indent=2, ensure_ascii=False) + "\n",
        encoding=encoding,
        newline="",
    )
    return path


@dataclass(frozen=True)
class DeployTraceWriteResult:
    """Result of writing deploy trace artifacts."""

    latest_path: Path
    archive_path: Path
    cr_dispatch: dict


def write_deploy_trace(
    *,
    run_label: str,
    plan_path: str | Path = "output/cr/latest/dispatch_plan.json",
    receipt_path: str | Path = "output/cr/latest/dispatch_receipts.json",
    config: DeployTraceConfig | None = None,
    created_at: str | None = None,
) -> DeployTraceWriteResult:
    """Read CR artifacts and write deploy trace JSON output.

    Parameters
    ----------
    run_label:
        Human-readable run label for archive naming.
    plan_path:
        Path to dispatch_plan.json.
    receipt_path:
        Path to dispatch_receipts.json.
    config:
        Deploy trace output config.
    created_at:
        ISO-8601 timestamp.  Defaults to utcnow.

    Returns
    -------
    DeployTraceWriteResult
    """
    if config is None:
        config = DeployTraceConfig()
    if created_at is None:
        created_at = datetime.now(timezone.utc).isoformat()

    # Read CR artifacts via A6a reader (read-only).
    trace = read_cr_deploy_trace(plan_path=plan_path, receipt_path=receipt_path)
    cr_dispatch = trace["cr_dispatch"]

    # Build deploy trace output.
    output = {
        "schema_version": DEPLOY_TRACE_SCHEMA_VERSION,
        "run_id": run_label,
        "created_at": created_at,
        "cr_dispatch": cr_dispatch,
    }

    # Write to latest + archive.
    paths = resolve_deploy_trace_paths(run_label=run_label, config=config)
    _write_json(paths.latest_path, output)
    _write_json(paths.archive_path, output)

    return DeployTraceWriteResult(
        latest_path=paths.latest_path,
        archive_path=paths.archive_path,
        cr_dispatch=cr_dispatch,
    )
