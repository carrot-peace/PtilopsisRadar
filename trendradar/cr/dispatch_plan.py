# coding=utf-8
"""
CR-A dispatch plan (PR9l, PR-CR-A2) v0.1.

Pure, side-effect-free planning layer for the CR-A automatic alert channel.

This module answers exactly one system question:

    Given a CRPipelineResult, is there a CR-A message that would be eligible
    to send, and what would its payload look like?

It produces a plan object only.  It performs no delivery, holds no recipient /
channel / token / parse-mode details, keeps no run-to-run state, and applies no
rate limiting.  Actual sending is a future PR.

Design reference: PR9l, PR-CR-A2.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Mapping

from trendradar.cr.decision import (
    DECISION_ALERT,
    DECISION_SUPPRESS,
    DECISION_URGENT,
    DECISION_WATCH,
)
from trendradar.cr.pipeline import CRPipelineResult
from trendradar.cr.presentation import CRPresentedCandidate
from trendradar.cr.event_identity import stable_event_key_for_candidate
from trendradar.cr.input_health import candidate_has_fresh_input


# ---------------------------------------------------------------------------
# Format constant
# ---------------------------------------------------------------------------

# Generic, channel-agnostic message format.  No per-channel parse mode yet.
FORMAT_PLAIN_TEXT = "plain_text"


# ---------------------------------------------------------------------------
# Dispatch plan JSON schema version
# ---------------------------------------------------------------------------

DISPATCH_PLAN_SCHEMA_VERSION = "cr-dispatch-plan-v1"


# ---------------------------------------------------------------------------
# Dispatch plan decision constants
# ---------------------------------------------------------------------------

DispatchPlanDecision = str

DECISION_DISPATCH: DispatchPlanDecision = "dispatch"
DECISION_NO_CANDIDATE: DispatchPlanDecision = "no_candidate"
DECISION_SUPPRESSED: DispatchPlanDecision = "suppress"
DECISION_COOLDOWN: DispatchPlanDecision = "cooldown"
DECISION_UNKNOWN: DispatchPlanDecision = "unknown"


# Map plan.reason → JSON decision.
_REASON_TO_DECISION: dict[str, DispatchPlanDecision] = {
    "ready": DECISION_DISPATCH,
    "ready_suppressed_only": DECISION_DISPATCH,
    "no_selected_candidates": DECISION_NO_CANDIDATE,
    "empty_text": DECISION_SUPPRESSED,
    "skipped_cooldown": DECISION_COOLDOWN,
    "skipped_repeat": DECISION_COOLDOWN,
    "skipped_state_error": DECISION_COOLDOWN,
    "deferred_quiet_hours": DECISION_DISPATCH,
    "quiet_hours_config_error": DECISION_SUPPRESSED,
    "skipped_deferred_queue_error": DECISION_SUPPRESSED,
    "skipped_deferred_queue_upsert": DECISION_SUPPRESSED,
    "stale_input": DECISION_SUPPRESSED,
    "insufficient_fresh_sources": DECISION_SUPPRESSED,
}


# ---------------------------------------------------------------------------
# Plan models
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class CRDispatchMessage:
    """A single planned CR-A message payload.

    Channel-agnostic: carries the rendered body and descriptive counts only.
    No recipient, chat id, token, parse mode, retry policy, or delivery
    metadata.
    """

    text: str
    format: str
    candidate_count: int
    run_label: str
    urgent_count: int
    high_score_suppressed_count: int
    html_path: str = ""


@dataclass(frozen=True)
class CRDispatchPlan:
    """The CR-A dispatch decision for one pipeline run.

    ``should_dispatch`` and ``reason`` describe whether a CR-A message would be
    eligible to send; ``messages`` carries the planned payload(s) when eligible
    (empty otherwise).  This object describes intent only — it sends nothing.
    """

    should_dispatch: bool
    messages: tuple[CRDispatchMessage, ...]
    reason: str
    run_label: str
    candidate_count: int
    urgent_count: int
    high_score_suppressed_count: int


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _count_urgent(candidates: tuple[CRPresentedCandidate, ...]) -> int:
    """Count candidates already decided at the ``urgent`` level.

    Reads the existing ``decision_level`` produced upstream — does NOT
    re-score or re-decide anything.
    """
    return sum(1 for c in candidates if c.decision_level == DECISION_URGENT)


def count_by_level(
    candidates: tuple[CRPresentedCandidate, ...] | list[CRPresentedCandidate],
) -> dict[str, int]:
    """Count candidates by decision level.

    Returns a dict with keys ``urgent``, ``alert``, ``watch``, ``suppress``.
    """
    counts: dict[str, int] = {
        DECISION_URGENT: 0,
        DECISION_ALERT: 0,
        DECISION_WATCH: 0,
        DECISION_SUPPRESS: 0,
    }
    for c in candidates:
        level = c.decision_level
        if level in counts:
            counts[level] += 1
    return counts


# ---------------------------------------------------------------------------
# Plan builder
# ---------------------------------------------------------------------------


def build_cr_a_dispatch_plan(
    pipeline: CRPipelineResult,
    *,
    min_candidate_count: int = 1,
    allow_empty_text: bool = False,
    html_path: str | Path | None = None,
) -> CRDispatchPlan:
    """Build a CR-A dispatch plan from a :class:`CRPipelineResult`.

    Pure: reads ``pipeline`` only, mutates nothing, and produces no side
    effects.  Uses the already-rendered ``cr_a_text`` and the already-selected
    ``cr_a_candidates``; it does not re-render text or recompute decisions.

    Parameters
    ----------
    pipeline:
        The completed CR pipeline result.
    min_candidate_count:
        Minimum number of selected CR-A candidates required to dispatch.
    allow_empty_text:
        When ``False`` (default), a blank ``cr_a_text`` blocks dispatch even if
        candidates are present.

    Blocked / ready semantics (evaluated in order):
      1. No selected candidates but ``high_score_suppressed_count > 0``
         → ``should_dispatch=True``, ``reason="ready_suppressed_only"``.
      2. ``len(cr_a_candidates) < min_candidate_count``
         → ``should_dispatch=False``, ``reason="no_selected_candidates"``.
      3. ``cr_a_text`` is blank and ``allow_empty_text`` is ``False``
         → ``should_dispatch=False``, ``reason="empty_text"``.
      4. otherwise
         → ``should_dispatch=True``, one message, ``reason="ready"``.

    Returns
    -------
    CRDispatchPlan
    """
    selected = pipeline.cr_a_candidates
    candidate_count = len(selected)
    urgent_count = _count_urgent(selected)
    high_score_suppressed_count = pipeline.high_score_suppressed_count
    normalized_html_path = str(html_path or "")

    # 1. A suppression-only run is operator-visible even though it has no
    # selected event candidate.  It uses the text already rendered by the
    # presentation layer and keeps candidate_count at zero.
    if candidate_count == 0 and high_score_suppressed_count > 0:
        if not allow_empty_text and not pipeline.cr_a_text.strip():
            return CRDispatchPlan(
                should_dispatch=False,
                messages=(),
                reason="empty_text",
                run_label=pipeline.run_label,
                candidate_count=0,
                urgent_count=0,
                high_score_suppressed_count=high_score_suppressed_count,
            )
        message = CRDispatchMessage(
            text=pipeline.cr_a_text,
            format=FORMAT_PLAIN_TEXT,
            candidate_count=0,
            run_label=pipeline.run_label,
            urgent_count=0,
            high_score_suppressed_count=high_score_suppressed_count,
            html_path=normalized_html_path,
        )
        return CRDispatchPlan(
            should_dispatch=True,
            messages=(message,),
            reason="ready_suppressed_only",
            run_label=pipeline.run_label,
            candidate_count=0,
            urgent_count=0,
            high_score_suppressed_count=high_score_suppressed_count,
        )

    # 2. Not enough selected candidates.
    if candidate_count < min_candidate_count:
        return CRDispatchPlan(
            should_dispatch=False,
            messages=(),
            reason="no_selected_candidates",
            run_label=pipeline.run_label,
            candidate_count=candidate_count,
            urgent_count=urgent_count,
            high_score_suppressed_count=high_score_suppressed_count,
        )

    # 3. Blank text guard.
    if not allow_empty_text and not pipeline.cr_a_text.strip():
        return CRDispatchPlan(
            should_dispatch=False,
            messages=(),
            reason="empty_text",
            run_label=pipeline.run_label,
            candidate_count=candidate_count,
            urgent_count=urgent_count,
            high_score_suppressed_count=high_score_suppressed_count,
        )

    # 4. Ready — exactly one planned message.
    message = CRDispatchMessage(
        text=pipeline.cr_a_text,
        format=FORMAT_PLAIN_TEXT,
        candidate_count=candidate_count,
        run_label=pipeline.run_label,
        urgent_count=urgent_count,
        high_score_suppressed_count=high_score_suppressed_count,
        html_path=normalized_html_path,
    )
    return CRDispatchPlan(
        should_dispatch=True,
        messages=(message,),
        reason="ready",
        run_label=pipeline.run_label,
        candidate_count=candidate_count,
        urgent_count=urgent_count,
        high_score_suppressed_count=high_score_suppressed_count,
    )


# ---------------------------------------------------------------------------
# JSON serialization
# ---------------------------------------------------------------------------


def cr_dispatch_plan_to_json_dict(
    plan: CRDispatchPlan,
    *,
    dispatch_mode: str,
    presented_candidates: tuple[CRPresentedCandidate, ...]
    | list[CRPresentedCandidate]
    | None = None,
    cr_a_candidates: tuple[CRPresentedCandidate, ...]
    | list[CRPresentedCandidate]
    | None = None,
    created_at: str | None = None,
    cooldown_context: dict[str, object] | None = None,
    quiet_hours_context: dict[str, object] | None = None,
    input_health: dict[str, object] | None = None,
) -> dict[str, object]:
    """Serialize a :class:`CRDispatchPlan` to a JSON-serializable dict.

    This is the authoritative JSON representation for one CR-A run.
    Deploy trace and future operator tools should prefer this JSON over
    parsing Markdown/HTML.

    Parameters
    ----------
    plan:
        The dispatch plan to serialize.
    dispatch_mode:
        The active dispatch mode (``artifact``, ``shadow``, or ``live``).
    presented_candidates:
        All presented candidates from the pipeline (not just CR-A selected).
        Used to populate ``candidate_summary`` and ``candidate_counts``.
        When ``None``, summary fields are empty.
    cr_a_candidates:
        The CR-A selected candidates (the actual dispatch targets).
        Used to populate ``selected_*`` fields.  When ``None``, falls back
        to scanning ``presented_candidates`` for backward compatibility.
    created_at:
        ISO-8601 timestamp string.  When ``None``, the field is ``None``.

    Returns
    -------
    dict
        JSON-serializable dict conforming to ``cr-dispatch-plan-v1``.
    """
    # --- Resolve decision ---
    decision = _REASON_TO_DECISION.get(plan.reason, DECISION_UNKNOWN)

    # --- Candidate summary ---
    candidate_summary: list[dict[str, object]] = []
    if presented_candidates is not None:
        for pc in presented_candidates:
            candidate: object = pc.candidate
            source_items = getattr(candidate, "source_items", None) or []
            source_ids: set[str] = set()
            for item in source_items:
                sid = getattr(item, "source_id", None)
                if sid:
                    source_ids.add(sid)
            candidate_summary.append(
                {
                    "candidate_id": pc.candidate_id,
                    "cluster_key": pc.cluster_key,
                    "title": pc.display_title,
                    "level": pc.decision_level,
                    "score": pc.total_score,
                    "push_eligible": pc.decision.push_eligible,
                    "trigger_reasons": list(pc.trigger_reasons),
                    "suppress_reasons": list(pc.suppress_labels),
                    "source_count": len(source_items),
                    "platform_count": len(source_ids),
                    "fresh_input_eligible": candidate_has_fresh_input(pc),
                }
            )

    # --- Candidate counts by level ---
    level_counts = count_by_level(presented_candidates or ())

    push_eligible_count = 0
    if presented_candidates is not None:
        push_eligible_count = sum(
            1 for pc in presented_candidates if pc.decision.push_eligible
        )

    candidate_counts = {
        "urgent": level_counts[DECISION_URGENT],
        "alert": level_counts[DECISION_ALERT],
        "watch": level_counts[DECISION_WATCH],
        "suppress": level_counts[DECISION_SUPPRESS],
        "push_eligible": push_eligible_count,
    }

    # --- Selected candidate (first CR-A candidate when dispatching) ---
    selected_event_key: str | None = None
    selected_candidate_id: str | None = None
    selected_title: str | None = None
    selected_level: str | None = None
    selected_score: float | None = None

    if plan.should_dispatch and plan.messages:
        # Prefer cr_a_candidates (the actual dispatch targets).
        # Fall back to scanning presented_candidates for backward compat.
        source = cr_a_candidates if cr_a_candidates else presented_candidates
        if plan.candidate_count > 0 and source:
            for pc in source:
                if pc.decision.push_eligible and pc.decision_level in (
                    DECISION_ALERT,
                    DECISION_URGENT,
                ):
                    selected_event_key = stable_event_key_for_candidate(pc)
                    selected_candidate_id = pc.candidate_id
                    selected_title = pc.display_title
                    selected_level = pc.decision_level
                    selected_score = pc.total_score
                    break

    # --- Message preview ---
    message_preview: str | None = None
    if plan.should_dispatch and plan.messages:
        message_preview = plan.messages[0].text

    # --- Missing fields ---
    missing_fields: list[str] = []
    if (
        selected_event_key is None
        and plan.should_dispatch
        and plan.candidate_count > 0
    ):
        missing_fields.append("selected_event_key")

    result = {
        "schema_version": DISPATCH_PLAN_SCHEMA_VERSION,
        "run_id": plan.run_label,
        "created_at": created_at,
        "dispatch_mode": dispatch_mode,
        "should_dispatch": plan.should_dispatch,
        "decision": decision,
        "reason": plan.reason,
        "selected_event_key": selected_event_key,
        "selected_candidate_id": selected_candidate_id,
        "selected_title": selected_title,
        "selected_level": selected_level,
        "selected_score": selected_score,
        "candidate_counts": candidate_counts,
        "candidate_summary": candidate_summary,
        "message_preview": message_preview,
        "missing_fields": missing_fields,
    }
    if cooldown_context is not None:
        result["cooldown"] = cooldown_context
    if quiet_hours_context is not None:
        result["quiet_hours"] = quiet_hours_context
    if input_health is not None:
        result["input_health"] = input_health
    return result
