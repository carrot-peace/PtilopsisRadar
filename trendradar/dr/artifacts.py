# coding=utf-8
"""DR dispatch artifact writing."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class DRDispatchArtifactPaths:
    plan_path: Path
    receipt_path: Path
    latest_plan_path: Path
    latest_receipt_path: Path


def write_dr_dispatch_artifacts(
    *,
    plan_json: dict[str, object],
    receipt_json: dict[str, object],
    run_label: str,
    base_dir: str | Path = "output/dr/dispatch",
) -> DRDispatchArtifactPaths:
    root = Path(base_dir)
    archive = root / "archive"
    latest = root / "latest"
    archive.mkdir(parents=True, exist_ok=True)
    latest.mkdir(parents=True, exist_ok=True)

    safe_label = "".join(
        ch if ch.isalnum() or ch in ("-", "_", ".") else "-" for ch in run_label
    ).strip("-") or "run"
    plan_path = archive / f"{safe_label}-plan.json"
    receipt_path = archive / f"{safe_label}-receipts.json"
    latest_plan_path = latest / "dispatch_plan.json"
    latest_receipt_path = latest / "dispatch_receipts.json"

    for path, payload in (
        (plan_path, plan_json),
        (receipt_path, receipt_json),
        (latest_plan_path, plan_json),
        (latest_receipt_path, receipt_json),
    ):
        path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )

    return DRDispatchArtifactPaths(
        plan_path=plan_path,
        receipt_path=receipt_path,
        latest_plan_path=latest_plan_path,
        latest_receipt_path=latest_receipt_path,
    )
