# coding=utf-8
"""
CR-A cooldown enforcement (PR-CR-A4) v0.1.

Connects the existing pure cooldown policy / repeat preview infrastructure to
actual dispatch suppression and state persistence.

This module answers:

    Given a dispatch plan, prior dispatch state, and a cooldown policy,
    should this CR-A run dispatch, skip, or escalate?

Main invariants:
  - Same event + same/lower level inside cooldown → skip
  - Same event + higher level → escalation bypass, may dispatch
  - Only live+accepted dispatch updates successful state
  - Malformed state → fail closed (skip)

Design reference: PR-CR-A4.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Mapping

from trendradar.cr.cooldown_policy import (
    ACTION_ALLOW_ESCALATION,
    ACTION_ALLOW_NEW,
    ACTION_COOLDOWN,
    CRCooldownDecision,
    CRCooldownPolicy,
    decide_cr_cooldown,
)
from trendradar.cr.decision import DECISION_ALERT, DECISION_URGENT, CRDecisionLevel
from trendradar.cr.event_identity import stable_event_key_for_candidate
from trendradar.cr.repeat_preview import (
    CRRepeatPreview,
    CRSeenEventState,
    preview_cr_repeat,
)
from trendradar.cr.state_snapshot import (
    CREventStateEntry,
    CREventStateSnapshot,
    cr_event_state_snapshot_to_seen_states,
)


# ---------------------------------------------------------------------------
# Dispatch state path
# ---------------------------------------------------------------------------

DEFAULT_DISPATCH_STATE_PATH = "output/cr/state/cr_dispatch_state.json"


# ---------------------------------------------------------------------------
# Severity order
# ---------------------------------------------------------------------------

_LEVEL_ORDER: dict[CRDecisionLevel, int] = {
    "suppress": 0,
    "watch": 1,
    "alert": 2,
    "urgent": 3,
}


# ---------------------------------------------------------------------------
# Enforcement result
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class CRCooldownEnforcementEntry:
    """Cooldown enforcement decision for one candidate."""

    event_key: str
    candidate_id: str
    current_level: str
    previous_level: str | None
    cooldown_action: str  # allow_new, allow_escalation, cooldown, not_evaluated
    is_escalation: bool
    cooldown_seconds: int | None
    cooldown_remaining_seconds: int | None


@dataclass(frozen=True)
class CRCooldownEnforcementResult:
    """Result of enforcing cooldown on a dispatch plan."""

    should_dispatch: bool
    override_reason: str | None  # None = no override, else skip reason
    entries: tuple[CRCooldownEnforcementEntry, ...]
    eligible_candidates: tuple  # CR-A candidates that passed cooldown
    state_available: bool
    state_error: str | None


# ---------------------------------------------------------------------------
# Enforcement logic
# ---------------------------------------------------------------------------


def _is_escalation(
    previous_level: CRDecisionLevel | None,
    current_level: CRDecisionLevel | None,
) -> bool:
    """Check if current level is higher than previous level."""
    if previous_level is None or current_level is None:
        return False
    prev_rank = _LEVEL_ORDER.get(previous_level)
    curr_rank = _LEVEL_ORDER.get(current_level)
    if prev_rank is None or curr_rank is None:
        return False
    return curr_rank > prev_rank


def _cooldown_seconds_for_level(
    level: CRDecisionLevel | None,
    policy: CRCooldownPolicy,
) -> int:
    """Get cooldown seconds for a given level."""
    return policy.same_level_cooldown_minutes * 60


def _compute_cooldown_remaining(
    last_dispatched_at: str | None,
    cooldown_seconds: int,
    now: datetime,
) -> int | None:
    """Compute remaining cooldown seconds. None if no prior dispatch."""
    if last_dispatched_at is None:
        return None
    try:
        last_dt = datetime.fromisoformat(last_dispatched_at)
        if last_dt.tzinfo is None:
            last_dt = last_dt.replace(tzinfo=timezone.utc)
        elapsed = (now - last_dt).total_seconds()
        remaining = cooldown_seconds - elapsed
        return max(0, int(remaining))
    except (ValueError, TypeError):
        return None


def enforce_cr_cooldown(
    *,
    event_key: str,
    candidate_id: str,
    current_level: CRDecisionLevel | None,
    seen_state: CRSeenEventState | None,
    prior_snapshot_provided: bool,
    policy: CRCooldownPolicy | None = None,
    now: datetime | None = None,
) -> CRCooldownEnforcementResult:
    """Enforce cooldown for one event/candidate.

    Parameters
    ----------
    event_key:
        The stable event identity key (title-derived, URL-agnostic).
    candidate_id:
        The candidate identifier.
    current_level:
        The current decision level (alert/urgent).
    seen_state:
        Prior dispatch state for this event, if available.
    prior_snapshot_provided:
        Whether a prior state snapshot was loaded (even if empty).
    policy:
        Cooldown policy. Defaults to CRCooldownPolicy().
    now:
        Current time. Defaults to utcnow.

    Returns
    -------
    CRCooldownEnforcementResult
    """
    if policy is None:
        policy = CRCooldownPolicy()
    if now is None:
        now = datetime.now(timezone.utc)

    # Build repeat preview using existing infrastructure.
    repeat_preview = preview_cr_repeat(
        event_key=event_key,
        current_decision_level=current_level,
        seen_state=seen_state,
        prior_state_snapshot_provided=prior_snapshot_provided,
    )

    # Build cooldown decision using existing infrastructure.
    cooldown_decision = decide_cr_cooldown(
        event_key=event_key,
        repeat_preview=repeat_preview,
        policy=policy,
    )

    # Determine escalation status.
    previous_level = seen_state.decision_level if seen_state else None
    escalation = _is_escalation(previous_level, current_level)

    # Compute cooldown timing.
    cooldown_seconds = _cooldown_seconds_for_level(current_level, policy)
    last_dispatched_at = seen_state.seen_at if seen_state else None
    remaining = _compute_cooldown_remaining(last_dispatched_at, cooldown_seconds, now)

    entry = CRCooldownEnforcementEntry(
        event_key=event_key,
        candidate_id=candidate_id,
        current_level=current_level or "unknown",
        previous_level=previous_level,
        cooldown_action=cooldown_decision.action,
        is_escalation=escalation,
        cooldown_seconds=cooldown_seconds,
        cooldown_remaining_seconds=remaining,
    )

    # Enforcement decision.
    action = cooldown_decision.action

    # Time-based cooldown check: even if repeat preview says "same_level_repeat",
    # check if cooldown has actually expired.
    if action == ACTION_COOLDOWN and seen_state is not None and seen_state.seen_at is not None:
        try:
            last_dt = datetime.fromisoformat(seen_state.seen_at)
            if last_dt.tzinfo is None:
                last_dt = last_dt.replace(tzinfo=timezone.utc)
            elapsed = (now - last_dt).total_seconds()
            if elapsed >= cooldown_seconds:
                # Cooldown expired — allow dispatch.
                action = ACTION_ALLOW_NEW
        except (ValueError, TypeError):
            pass  # Keep original action

    if action == ACTION_ALLOW_NEW:
        return CRCooldownEnforcementResult(
            should_dispatch=True,
            override_reason=None,
            entries=(entry,),
            eligible_candidates=(),  # caller fills this
            state_available=prior_snapshot_provided,
            state_error=None,
        )

    if action == ACTION_ALLOW_ESCALATION:
        return CRCooldownEnforcementResult(
            should_dispatch=True,
            override_reason=None,
            entries=(entry,),
            eligible_candidates=(),
            state_available=prior_snapshot_provided,
            state_error=None,
        )

    if action == ACTION_COOLDOWN:
        # Distinguish repeat vs cooldown based on repeat preview status.
        if repeat_preview.status in ("same_level_repeat", "same_event_repeat"):
            reason = "skipped_repeat"
        else:
            reason = "skipped_cooldown"
        return CRCooldownEnforcementResult(
            should_dispatch=False,
            override_reason=reason,
            entries=(entry,),
            eligible_candidates=(),
            state_available=prior_snapshot_provided,
            state_error=None,
        )

    # not_evaluated or unknown — allow (don't block on missing data).
    return CRCooldownEnforcementResult(
        should_dispatch=True,
        override_reason=None,
        entries=(entry,),
        eligible_candidates=(),
        state_available=prior_snapshot_provided,
        state_error=None,
    )


def enforce_cr_cooldown_for_candidates(
    *,
    cr_a_candidates: tuple,
    seen_states: Mapping[str, CRSeenEventState] | None,
    prior_snapshot_provided: bool,
    state_error: str | None = None,
    policy: CRCooldownPolicy | None = None,
    now: datetime | None = None,
) -> CRCooldownEnforcementResult:
    """Enforce cooldown for all CR-A selected candidates.

    Per-candidate enforcement: each candidate is evaluated independently.
    Escalation bypass applies per-candidate, not globally.
    Returns only eligible candidates in ``eligible_candidates``.

    When ``state_error`` is set (malformed/invalid state), fails closed:
    no candidates are eligible and dispatch is blocked.
    """
    if not cr_a_candidates:
        return CRCooldownEnforcementResult(
            should_dispatch=True,
            override_reason=None,
            entries=(),
            eligible_candidates=(),
            state_available=prior_snapshot_provided,
            state_error=state_error,
        )

    # Blocker 1: fail closed on state errors.
    if state_error is not None:
        entries = tuple(
            CRCooldownEnforcementEntry(
                event_key=stable_event_key_for_candidate(pc),
                candidate_id=pc.candidate_id,
                current_level=pc.decision_level or "unknown",
                previous_level=None,
                cooldown_action="not_evaluated",
                is_escalation=False,
                cooldown_seconds=None,
                cooldown_remaining_seconds=None,
            )
            for pc in cr_a_candidates
        )
        return CRCooldownEnforcementResult(
            should_dispatch=False,
            override_reason="skipped_state_error",
            entries=entries,
            eligible_candidates=(),
            state_available=False,
            state_error=state_error,
        )

    entries: list[CRCooldownEnforcementEntry] = []
    eligible: list = []

    for pc in cr_a_candidates:
        event_key = stable_event_key_for_candidate(pc)
        seen = seen_states.get(event_key) if seen_states else None

        result = enforce_cr_cooldown(
            event_key=event_key,
            candidate_id=pc.candidate_id,
            current_level=pc.decision_level,
            seen_state=seen,
            prior_snapshot_provided=prior_snapshot_provided,
            policy=policy,
            now=now,
        )
        entries.extend(result.entries)

        if result.should_dispatch:
            eligible.append(pc)

    any_blocked = len(eligible) < len(list(cr_a_candidates))
    has_eligible = len(eligible) > 0

    if not any_blocked:
        return CRCooldownEnforcementResult(
            should_dispatch=True,
            override_reason=None,
            entries=tuple(entries),
            eligible_candidates=tuple(eligible),
            state_available=prior_snapshot_provided,
            state_error=None,
        )

    if has_eligible:
        # Some candidates passed (escalation or new), some blocked.
        # Allow dispatch with filtered candidate set.
        return CRCooldownEnforcementResult(
            should_dispatch=True,
            override_reason=None,
            entries=tuple(entries),
            eligible_candidates=tuple(eligible),
            state_available=prior_snapshot_provided,
            state_error=None,
        )

    # All candidates blocked.
    block_reason = "skipped_cooldown"
    for e in entries:
        if e.cooldown_action == "cooldown":
            block_reason = "skipped_cooldown"
            break
    return CRCooldownEnforcementResult(
        should_dispatch=False,
        override_reason=block_reason,
        entries=tuple(entries),
        eligible_candidates=(),
        state_available=prior_snapshot_provided,
        state_error=None,
    )
