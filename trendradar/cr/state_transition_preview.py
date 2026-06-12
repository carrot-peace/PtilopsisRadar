# coding=utf-8
"""
Pure CR-A event state transition preview (PR10i).

Builds an in-memory preview of what the next event state snapshot would look
like after applying proposed cooldown audit state updates.

This module is preview-only and intentionally inert:

  * no filesystem
  * no network
  * no environment
  * no delivery integration
  * no message planning integration
  * no application entrypoint integration
  * no project settings integration
  * no current time read
  * no randomness
  * no filesystem store boundary

It never writes state and never persists the preview.
"""

from __future__ import annotations

from dataclasses import dataclass

from trendradar.cr.state_snapshot import (
    CREventStateEntry,
    CREventStateSnapshot,
    empty_cr_event_state_snapshot,
    merge_cr_event_state_entries,
)


@dataclass(frozen=True)
class CREventStateTransitionPreview:
    """Preview of a cooldown audit state transition.

    ``next_snapshot`` is an in-memory preview only. It is never written here.
    """

    prior_snapshot_available: bool
    prior_snapshot_loaded: bool | None
    prior_snapshot_error: str | None
    update_count: int
    next_snapshot: CREventStateSnapshot | None
    reason: str


def build_cr_event_state_transition_preview(
    *,
    prior_snapshot: CREventStateSnapshot | None,
    state_updates: tuple[CREventStateEntry, ...],
    prior_snapshot_loaded: bool | None = None,
    prior_snapshot_error: str | None = None,
) -> CREventStateTransitionPreview:
    """Build an in-memory next-state preview from prior state and updates.

    Semantics:
    * prior load error -> fail closed and suppress the next-state preview
    * prior snapshot supplied -> merge prior snapshot with current updates
    * no prior snapshot supplied -> preview from current updates only
    """
    update_count = len(state_updates)

    if prior_snapshot_error is not None:
        return CREventStateTransitionPreview(
            prior_snapshot_available=False,
            prior_snapshot_loaded=prior_snapshot_loaded,
            prior_snapshot_error=prior_snapshot_error,
            update_count=update_count,
            next_snapshot=None,
            reason="prior snapshot failed to load; next-state preview suppressed",
        )

    if prior_snapshot is None:
        next_snapshot = merge_cr_event_state_entries(
            empty_cr_event_state_snapshot(),
            state_updates,
        )
        return CREventStateTransitionPreview(
            prior_snapshot_available=False,
            prior_snapshot_loaded=prior_snapshot_loaded,
            prior_snapshot_error=None,
            update_count=update_count,
            next_snapshot=next_snapshot,
            reason=(
                "no prior snapshot supplied; preview uses current state "
                "updates only"
            ),
        )

    next_snapshot = merge_cr_event_state_entries(prior_snapshot, state_updates)
    return CREventStateTransitionPreview(
        prior_snapshot_available=True,
        prior_snapshot_loaded=prior_snapshot_loaded,
        prior_snapshot_error=None,
        update_count=update_count,
        next_snapshot=next_snapshot,
        reason="prior snapshot merged with current state updates",
    )
