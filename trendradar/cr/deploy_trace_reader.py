# coding=utf-8
"""
CR-A deploy trace reader (PR-CR-A6a) v0.1.

Reads authoritative CR-A dispatch plan and receipt JSON artifacts and produces
a deploy trace observation dict.

This module is read-only with respect to CR artifacts and CR state.  It does
not send Telegram, does not mutate dispatch state, and does not regenerate
CR plan/receipt artifacts.

Design reference: PR-CR-A6a.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

DEFAULT_PLAN_PATH = "output/cr/latest/dispatch_plan.json"
DEFAULT_RECEIPT_PATH = "output/cr/latest/dispatch_receipts.json"


# ---------------------------------------------------------------------------
# Result model
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class CRArtifactReadResult:
    """Result of reading one CR artifact file."""

    available: bool
    data: dict | None = None
    parse_error: str | None = None
    path: str | None = None


# ---------------------------------------------------------------------------
# Reader
# ---------------------------------------------------------------------------


def _safe_parse_error(exc: BaseException) -> str:
    """Produce a short, safe parse-error string."""
    msg = str(exc).strip()
    if not msg:
        msg = type(exc).__name__
    if len(msg) > 96:
        msg = msg[:93] + "..."
    return msg


def _read_artifact(path: str | Path) -> CRArtifactReadResult:
    """Read and parse a single JSON artifact file."""
    p = Path(path)
    result_path = str(p)

    if not p.exists():
        return CRArtifactReadResult(
            available=False, data=None, parse_error=None, path=result_path,
        )

    try:
        raw = json.loads(p.read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            raise ValueError("artifact root must be a JSON object")
        return CRArtifactReadResult(
            available=True, data=raw, parse_error=None, path=result_path,
        )
    except (json.JSONDecodeError, ValueError, OSError) as exc:
        return CRArtifactReadResult(
            available=True, data=None, parse_error=_safe_parse_error(exc),
            path=result_path,
        )


def _extract_selected_candidate(plan: dict) -> dict[str, object]:
    """Extract selected candidate fields from plan data."""
    return {
        "event_key": plan.get("selected_event_key"),
        "candidate_id": plan.get("selected_candidate_id"),
        "title": plan.get("selected_title"),
        "level": plan.get("selected_level"),
        "score": plan.get("selected_score"),
    }


def _extract_receipt_summary(receipt: dict) -> dict[str, object]:
    """Extract receipt summary from the first message-level receipt."""
    receipts = receipt.get("receipts", [])
    if not receipts:
        return {
            "attempted": False,
            "accepted": False,
            "status": "unknown",
            "detail": None,
        }
    first = receipts[0]
    return {
        "attempted": first.get("attempted", False),
        "accepted": first.get("accepted", False),
        "status": first.get("status", "unknown"),
        "detail": first.get("detail"),
    }


def _extract_cooldown(plan: dict) -> dict[str, object] | None:
    """Extract cooldown context from plan data."""
    return plan.get("cooldown")


def _extract_candidate_outcomes(receipt: dict, plan: dict) -> list[dict[str, object]]:
    """Extract candidate outcomes from receipt or plan."""
    outcomes = receipt.get("candidate_outcomes")
    if outcomes:
        return outcomes
    cooldown = plan.get("cooldown")
    if cooldown and "entries" in cooldown:
        return cooldown["entries"]
    return []


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def read_cr_deploy_trace(
    *,
    plan_path: str | Path = DEFAULT_PLAN_PATH,
    receipt_path: str | Path = DEFAULT_RECEIPT_PATH,
) -> dict[str, object]:
    """Read CR-A dispatch plan and receipt artifacts and produce a deploy trace.

    Parameters
    ----------
    plan_path:
        Path to dispatch_plan.json.
    receipt_path:
        Path to dispatch_receipts.json.

    Returns
    -------
    dict
        Deploy trace observation dict with ``cr_dispatch`` section.
    """
    plan_result = _read_artifact(plan_path)
    receipt_result = _read_artifact(receipt_path)

    # Determine decision source and confidence.
    has_plan = plan_result.available and plan_result.data is not None
    has_receipt = receipt_result.available and receipt_result.data is not None
    plan_parse_error = plan_result.parse_error
    receipt_parse_error = receipt_result.parse_error

    if plan_parse_error or receipt_parse_error:
        decision_source = "artifact_parse_error"
        confidence = "low"
    elif has_plan and has_receipt:
        decision_source = "authoritative_plan_receipt"
        confidence = "high"
    elif has_plan:
        decision_source = "authoritative_plan_only"
        confidence = "medium"
    elif has_receipt:
        decision_source = "authoritative_receipt_only"
        confidence = "medium"
    else:
        decision_source = "missing_artifacts"
        confidence = "low"

    # Build the CR dispatch section.
    cr_dispatch: dict[str, object] = {
        "decision_source": decision_source,
        "confidence": confidence,
        "plan_path": str(plan_path),
        "receipt_path": str(receipt_path),
        "plan_available": plan_result.available,
        "receipt_available": receipt_result.available,
        "plan_parse_error": plan_parse_error,
        "receipt_parse_error": receipt_parse_error,
    }

    # Schema versions.
    schema_version: dict[str, str | None] = {
        "plan": None,
        "receipt": None,
    }
    if has_plan:
        schema_version["plan"] = plan_result.data.get("schema_version")
    if has_receipt:
        schema_version["receipt"] = receipt_result.data.get("schema_version")
    cr_dispatch["schema_version"] = schema_version

    # Plan fields.
    plan_data = plan_result.data if has_plan else {}
    cr_dispatch["run_id"] = plan_data.get("run_id") or (
        receipt_result.data.get("run_id") if has_receipt else None
    )
    cr_dispatch["dispatch_mode"] = plan_data.get("dispatch_mode") or (
        receipt_result.data.get("dispatch_mode") if has_receipt else None
    )
    cr_dispatch["plan_decision"] = plan_data.get("decision") or (
        receipt_result.data.get("plan_decision") if has_receipt else None
    )
    cr_dispatch["plan_reason"] = plan_data.get("reason")
    cr_dispatch["plan_should_dispatch"] = plan_data.get("should_dispatch")

    # Selected candidate.
    cr_dispatch["selected_candidate"] = _extract_selected_candidate(plan_data)

    # Cooldown.
    cr_dispatch["cooldown"] = _extract_cooldown(plan_data)

    # Receipt summary.
    receipt_data = receipt_result.data if has_receipt else {}
    cr_dispatch["receipt_summary"] = _extract_receipt_summary(receipt_data)

    # Candidate outcomes.
    cr_dispatch["candidate_outcomes"] = _extract_candidate_outcomes(
        receipt_data, plan_data,
    )

    return {"cr_dispatch": cr_dispatch}
