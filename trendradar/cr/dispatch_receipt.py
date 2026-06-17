# coding=utf-8
"""
CR-A dispatch receipt JSON serialization (PR-CR-A3) v0.1.

Pure, side-effect-free layer that answers exactly one system question:

    Given a CR dispatch plan and its execution result, what structured receipt
    should be persisted as JSON?

It produces a JSON-serializable dict only.  It performs no delivery, holds no
channel details, and writes no files.  Artifact writing is handled by the
artifact layer.

Design reference: PR-CR-A3.
"""

from __future__ import annotations

from trendradar.cr.dispatch_executor import CRDispatchExecutionResult, CRDispatchReceipt
from trendradar.cr.dispatch_plan import CRDispatchPlan


# ---------------------------------------------------------------------------
# Schema version
# ---------------------------------------------------------------------------

DISPATCH_RECEIPT_SCHEMA_VERSION = "cr-dispatch-receipts-v1"


# ---------------------------------------------------------------------------
# Status vocabulary
# ---------------------------------------------------------------------------

STATUS_NOT_EXECUTED = "not_executed"
STATUS_SHADOW_ONLY = "shadow_only"
STATUS_SKIPPED_NO_CANDIDATE = "skipped_no_candidate"
STATUS_SKIPPED_SUPPRESS = "skipped_suppress"
STATUS_SKIPPED_COOLDOWN = "skipped_cooldown"
STATUS_SKIPPED_REPEAT = "skipped_repeat"
STATUS_SKIPPED_STATE_ERROR = "skipped_state_error"
STATUS_NOT_CONFIGURED = "not_configured"
STATUS_ACCEPTED = "accepted"
STATUS_REJECTED = "rejected"
STATUS_FAILED_TRANSPORT = "failed_transport"
STATUS_FAILED_RENDER = "failed_render"
STATUS_HTTP_ERROR = "http_error"
STATUS_UNKNOWN = "unknown"


# ---------------------------------------------------------------------------
# Receipt status resolution
# ---------------------------------------------------------------------------


def _resolve_receipt_status(
    execution_receipt: CRDispatchReceipt,
) -> str:
    """Map an execution receipt status to the JSON receipt status vocabulary."""
    mapping = {
        "accepted": STATUS_ACCEPTED,
        "rejected": STATUS_REJECTED,
        "failed_transport": STATUS_FAILED_TRANSPORT,
        "http_error": STATUS_HTTP_ERROR,
    }
    return mapping.get(execution_receipt.status, STATUS_UNKNOWN)


def _build_receipt_entry(
    execution_receipt: CRDispatchReceipt,
) -> dict[str, object]:
    """Build a single receipt entry from an execution receipt."""
    status = _resolve_receipt_status(execution_receipt)
    return {
        "message_index": execution_receipt.message_index,
        "attempted": True,
        "accepted": execution_receipt.accepted,
        "status": status,
        "detail": execution_receipt.detail,
        "transport": None,
        "http_status": None,
        "sink_ok": None,
        "exception_type": None,
        "exception_message": None,
    }


def _build_skipped_receipt_entry(
    message_index: int,
    status: str,
    detail: str,
) -> dict[str, object]:
    """Build a receipt entry for a skipped / not-executed plan."""
    return {
        "message_index": message_index,
        "attempted": False,
        "accepted": False,
        "status": status,
        "detail": detail,
        "transport": None,
        "http_status": None,
        "sink_ok": None,
        "exception_type": None,
        "exception_message": None,
    }


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def build_dispatch_receipts_json(
    plan: CRDispatchPlan,
    *,
    dispatch_mode: str,
    execution: CRDispatchExecutionResult | None = None,
    created_at: str | None = None,
    cooldown_override_reason: str | None = None,
    cooldown_entries: list[dict[str, object]] | None = None,
) -> dict[str, object]:
    """Build the dispatch receipts JSON dict.

    Parameters
    ----------
    plan:
        The dispatch plan that was executed (or skipped).
    dispatch_mode:
        The active dispatch mode (``artifact``, ``shadow``, or ``live``).
    execution:
        The execution result.  ``None`` when no sink was provided.
    created_at:
        ISO-8601 timestamp string.
    cooldown_override_reason:
        When set, the plan was overridden by cooldown enforcement.
        Receipt status reflects this override (skipped_cooldown, skipped_repeat,
        skipped_state_error).
    cooldown_entries:
        Per-candidate cooldown outcomes from enforcement.  When provided,
        included in the receipt as ``candidate_outcomes``.

    Returns
    -------
    dict
        JSON-serializable dict conforming to ``cr-dispatch-receipts-v1``.
    """
    # --- Cooldown override (applies to all modes) ---
    if cooldown_override_reason is not None:
        receipts = [
            _build_skipped_receipt_entry(0, cooldown_override_reason, cooldown_override_reason)
        ]
    # --- Mode-level skip (no execution possible) ---
    elif dispatch_mode == "artifact":
        receipts = _mode_receipts(plan, STATUS_NOT_EXECUTED, "artifact_mode_no_send")
    elif dispatch_mode == "shadow":
        receipts = _mode_receipts(plan, STATUS_SHADOW_ONLY, "shadow_mode_no_send")
    elif not plan.should_dispatch:
        # Live mode but plan didn't dispatch.
        receipts = _plan_skip_receipts(plan)
    elif execution is None:
        # Live mode, plan ready, but no sink configured.
        receipts = [
            _build_skipped_receipt_entry(0, STATUS_NOT_CONFIGURED, "no_sink_configured")
        ]
    else:
        # Live mode with execution.
        receipts = _execution_receipts(execution)

    result: dict[str, object] = {
        "schema_version": DISPATCH_RECEIPT_SCHEMA_VERSION,
        "run_id": plan.run_label,
        "created_at": created_at,
        "dispatch_mode": dispatch_mode,
        "plan_decision": _plan_decision(plan),
        "plan_should_dispatch": plan.should_dispatch,
        "receipts": receipts,
    }
    if cooldown_entries:
        result["candidate_outcomes"] = cooldown_entries
    return result


# ---------------------------------------------------------------------------
# Internal builders
# ---------------------------------------------------------------------------


def _plan_decision(plan: CRDispatchPlan) -> str:
    """Derive a decision label from the plan reason."""
    from trendradar.cr.dispatch_plan import _REASON_TO_DECISION, DECISION_UNKNOWN
    return _REASON_TO_DECISION.get(plan.reason, DECISION_UNKNOWN)


def _mode_receipts(
    plan: CRDispatchPlan,
    status: str,
    detail: str,
) -> list[dict[str, object]]:
    """Build receipts for a mode-level skip (artifact/shadow)."""
    if plan.should_dispatch and plan.messages:
        return [
            _build_skipped_receipt_entry(i, status, detail)
            for i in range(len(plan.messages))
        ]
    return [_build_skipped_receipt_entry(0, status, detail)]


def _plan_skip_receipts(plan: CRDispatchPlan) -> list[dict[str, object]]:
    """Build receipts for a plan-level skip (no candidate / suppress)."""
    if plan.reason == "no_selected_candidates":
        status = STATUS_SKIPPED_NO_CANDIDATE
        detail = "no_selected_candidates"
    elif plan.reason == "empty_text":
        status = STATUS_SKIPPED_SUPPRESS
        detail = "empty_text"
    else:
        status = STATUS_UNKNOWN
        detail = plan.reason
    return [_build_skipped_receipt_entry(0, status, detail)]


def _execution_receipts(
    execution: CRDispatchExecutionResult,
) -> list[dict[str, object]]:
    """Build receipts from an execution result."""
    if not execution.receipts:
        return [
            _build_skipped_receipt_entry(0, STATUS_UNKNOWN, "no_receipts")
        ]
    return [_build_receipt_entry(r) for r in execution.receipts]
