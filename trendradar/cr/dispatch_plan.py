# coding=utf-8
"""
CR-A dispatch plan (PR9l) v0.1.

Pure, side-effect-free planning layer for the CR-A automatic alert channel.

This module answers exactly one system question:

    Given a CRPipelineResult, is there a CR-A message that would be eligible
    to send, and what would its payload look like?

It produces a plan object only.  It performs no delivery, holds no recipient /
channel / token / parse-mode details, keeps no run-to-run state, and applies no
rate limiting.  Actual sending is a future PR.

Design reference: PR9l.
"""

from __future__ import annotations

from dataclasses import dataclass

from trendradar.cr.decision import DECISION_URGENT
from trendradar.cr.pipeline import CRPipelineResult
from trendradar.cr.presentation import CRPresentedCandidate


# ---------------------------------------------------------------------------
# Format constant
# ---------------------------------------------------------------------------

# Generic, channel-agnostic message format.  No per-channel parse mode yet.
FORMAT_PLAIN_TEXT = "plain_text"


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


# ---------------------------------------------------------------------------
# Plan builder
# ---------------------------------------------------------------------------


def build_cr_a_dispatch_plan(
    pipeline: CRPipelineResult,
    *,
    min_candidate_count: int = 1,
    allow_empty_text: bool = False,
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
      1. ``len(cr_a_candidates) < min_candidate_count``
         → ``should_dispatch=False``, ``reason="no_selected_candidates"``.
      2. ``cr_a_text`` is blank and ``allow_empty_text`` is ``False``
         → ``should_dispatch=False``, ``reason="empty_text"``.
      3. otherwise
         → ``should_dispatch=True``, one message, ``reason="ready"``.

    Returns
    -------
    CRDispatchPlan
    """
    selected = pipeline.cr_a_candidates
    candidate_count = len(selected)
    urgent_count = _count_urgent(selected)
    high_score_suppressed_count = pipeline.high_score_suppressed_count

    # 1. Not enough selected candidates.
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

    # 2. Blank text guard.
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

    # 3. Ready — exactly one planned message.
    message = CRDispatchMessage(
        text=pipeline.cr_a_text,
        format=FORMAT_PLAIN_TEXT,
        candidate_count=candidate_count,
        run_label=pipeline.run_label,
        urgent_count=urgent_count,
        high_score_suppressed_count=high_score_suppressed_count,
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
