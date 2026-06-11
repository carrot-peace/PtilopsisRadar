# coding=utf-8
"""
CR-A repeat preview evidence (PR10b).

Pure, deterministic helpers that classify how a current event would be
interpreted against an explicitly supplied in-memory prior state snapshot.

This module is observability-only. It does NOT enforce repeat suppression,
does NOT enforce cooldown, does NOT persist state, and does NOT touch
Telegram. It is intentionally pure:

  * no filesystem
  * no network
  * no environment
  * no Telegram
  * no storage
  * no timestamps generated internally
  * no randomness
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Mapping

from trendradar.cr.decision import (
    DECISION_ALERT,
    DECISION_SUPPRESS,
    DECISION_URGENT,
    DECISION_WATCH,
    CRDecisionLevel,
)


CRRepeatPreviewStatus = Literal[
    "not_evaluated",
    "new",
    "same_event_repeat",
    "same_level_repeat",
    "meaningful_escalation",
    "deescalation",
]

CRDecisionLevelComparison = Literal[
    "unknown",
    "same",
    "escalation",
    "deescalation",
]


@dataclass(frozen=True)
class CRSeenEventState:
    """Explicit prior state for one observed event key."""

    event_key: str
    decision_level: CRDecisionLevel | None = None
    score: float | None = None
    seen_at: str | None = None
    title: str | None = None
    candidate_id: str | None = None


@dataclass(frozen=True)
class CRRepeatPreview:
    """Audit-only repeat classification for one current event."""

    event_key: str
    status: CRRepeatPreviewStatus
    reason: str
    current_decision_level: CRDecisionLevel | None = None
    previous_decision_level: CRDecisionLevel | None = None
    current_score: float | None = None
    previous_score: float | None = None
    previous_seen_at: str | None = None


_LEVEL_ORDER: dict[CRDecisionLevel, int] = {
    DECISION_SUPPRESS: 0,
    DECISION_WATCH: 1,
    DECISION_ALERT: 2,
    DECISION_URGENT: 3,
}


def normalize_cr_decision_level(value: str | None) -> CRDecisionLevel | None:
    """Normalize an existing CR decision label without guessing aggressively."""
    if value is None:
        return None
    normalized = value.strip().lower()
    if normalized == DECISION_SUPPRESS:
        return DECISION_SUPPRESS
    if normalized == DECISION_WATCH:
        return DECISION_WATCH
    if normalized == DECISION_ALERT:
        return DECISION_ALERT
    if normalized == DECISION_URGENT:
        return DECISION_URGENT
    return None


def compare_cr_decision_level(
    previous: CRDecisionLevel | None,
    current: CRDecisionLevel | None,
) -> CRDecisionLevelComparison:
    """Compare two CR decision levels using suppress < watch < alert < urgent."""
    if previous is None or current is None:
        return "unknown"
    previous_rank = _LEVEL_ORDER.get(previous)
    current_rank = _LEVEL_ORDER.get(current)
    if previous_rank is None or current_rank is None:
        return "unknown"
    if previous_rank == current_rank:
        return "same"
    if current_rank > previous_rank:
        return "escalation"
    return "deescalation"


def preview_cr_repeat(
    *,
    event_key: str,
    current_decision_level: CRDecisionLevel | None,
    current_score: float | None = None,
    seen_state: CRSeenEventState | None = None,
    prior_state_snapshot_provided: bool = False,
) -> CRRepeatPreview:
    """Preview repeat semantics for one current event.

    ``seen_state`` is never mutated. When no prior snapshot was provided, the
    status is ``not_evaluated``. When a snapshot was provided but the event key
    is absent, callers pass ``prior_state_snapshot_provided=True`` with
    ``seen_state=None`` and the status is ``new``.
    """
    current_level = normalize_cr_decision_level(current_decision_level)

    if seen_state is None:
        if prior_state_snapshot_provided:
            return CRRepeatPreview(
                event_key=event_key,
                status="new",
                reason="event key not present in prior state snapshot",
                current_decision_level=current_level,
                current_score=current_score,
            )
        return CRRepeatPreview(
            event_key=event_key,
            status="not_evaluated",
            reason="no prior event state snapshot provided",
            current_decision_level=current_level,
            current_score=current_score,
        )

    if seen_state.event_key != event_key:
        return CRRepeatPreview(
            event_key=event_key,
            status="new",
            reason="seen state event key does not match current event key",
            current_decision_level=current_level,
            current_score=current_score,
        )

    previous_level = normalize_cr_decision_level(seen_state.decision_level)
    comparison = compare_cr_decision_level(previous_level, current_level)

    if comparison == "same":
        status: CRRepeatPreviewStatus = "same_level_repeat"
        reason = "same event key and same decision level"
    elif comparison == "escalation":
        status = "meaningful_escalation"
        reason = "same event key and higher current decision level"
    elif comparison == "deescalation":
        status = "deescalation"
        reason = "same event key and lower current decision level"
    else:
        status = "same_event_repeat"
        reason = "same event key but decision levels are unavailable"

    return CRRepeatPreview(
        event_key=event_key,
        status=status,
        reason=reason,
        current_decision_level=current_level,
        previous_decision_level=previous_level,
        current_score=current_score,
        previous_score=seen_state.score,
        previous_seen_at=seen_state.seen_at,
    )


def preview_cr_repeats(
    current_events: tuple[tuple[str, CRDecisionLevel | None, float | None], ...],
    *,
    seen_states: Mapping[str, CRSeenEventState] | None = None,
) -> tuple[CRRepeatPreview, ...]:
    """Preview repeat semantics for a batch while preserving input order."""
    previews: list[CRRepeatPreview] = []
    snapshot_provided = seen_states is not None
    for event_key, current_level, current_score in current_events:
        seen_state = seen_states.get(event_key) if seen_states is not None else None
        previews.append(
            preview_cr_repeat(
                event_key=event_key,
                current_decision_level=current_level,
                current_score=current_score,
                seen_state=seen_state,
                prior_state_snapshot_provided=snapshot_provided,
            )
        )
    return tuple(previews)
