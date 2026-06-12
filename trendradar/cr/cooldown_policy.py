# coding=utf-8
"""
CR-A cooldown policy decision layer (PR10d).

Pure, deterministic helpers that answer a single question:

  "Given a repeat preview and a cooldown policy, what would the cooldown
  decision be?"

This module is a *policy decision object only*. It is observability-only and
intentionally inert with respect to runtime behavior. It does NOT:

  * suppress dispatch
  * enforce cooldown
  * read or write event state
  * touch Telegram
  * read config.yaml or environment variables
  * read the current time or any clock
  * use randomness

It only computes what a cooldown policy *would* decide for a candidate, given
an explicitly supplied repeat preview. Actual enforcement (if ever) belongs to
a later, explicitly gated PR.

The module is pure:

  * no filesystem
  * no network
  * no environment
  * no Telegram
  * no storage
  * no current time read
  * no randomness
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from trendradar.cr.repeat_preview import CRRepeatPreview


# ---------------------------------------------------------------------------
# Action type
# ---------------------------------------------------------------------------

CRCooldownAction = Literal[
    "not_evaluated",
    "allow",
    "cooldown",
    "allow_escalation",
    "allow_new",
]

ACTION_NOT_EVALUATED: CRCooldownAction = "not_evaluated"
ACTION_ALLOW: CRCooldownAction = "allow"
ACTION_COOLDOWN: CRCooldownAction = "cooldown"
ACTION_ALLOW_ESCALATION: CRCooldownAction = "allow_escalation"
ACTION_ALLOW_NEW: CRCooldownAction = "allow_new"


# ---------------------------------------------------------------------------
# Policy
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class CRCooldownPolicy:
    """Policy that governs how a repeat preview maps to a cooldown action.

    This is a function-parameter default only; it does NOT connect to the
    project runtime config (config.yaml) and does NOT enforce anything.
    """

    same_level_cooldown_minutes: int = 60
    allow_meaningful_escalation: bool = True
    allow_new_events: bool = True
    allow_deescalation: bool = False


DEFAULT_CR_COOLDOWN_POLICY = CRCooldownPolicy()


# ---------------------------------------------------------------------------
# Decision result
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class CRCooldownDecision:
    """Audit-only cooldown policy decision for one event.

    Carries the resolved action plus the evidence that produced it. Does NOT
    carry any runtime mutation fields (sent, suppressed, cooldown_applied,
    state_written, ...).
    """

    event_key: str
    action: CRCooldownAction
    reason: str
    repeat_status: str | None = None
    current_decision_level: str | None = None
    previous_decision_level: str | None = None
    current_score: float | None = None
    previous_score: float | None = None
    cooldown_minutes: int | None = None


# ---------------------------------------------------------------------------
# Single decision
# ---------------------------------------------------------------------------


def decide_cr_cooldown(
    *,
    event_key: str,
    repeat_preview: CRRepeatPreview | None,
    policy: CRCooldownPolicy | None = None,
) -> CRCooldownDecision:
    """Decide what a cooldown policy would do for one event.

    Pure: no side effects, no clock read, no state access. The decision is a
    *preview* of what enforcement would do, not enforcement itself.

    Semantics
    ---------
    * ``repeat_preview is None`` -> ``not_evaluated``
    * ``repeat_status == "not_evaluated"`` -> ``not_evaluated``
    * ``repeat_status == "new"`` -> ``allow_new`` if ``policy.allow_new_events``
      else ``cooldown``
    * ``repeat_status == "same_level_repeat"`` -> ``cooldown``
    * ``repeat_status == "same_event_repeat"`` -> ``cooldown``
    * ``repeat_status == "meaningful_escalation"`` -> ``allow_escalation`` if
      ``policy.allow_meaningful_escalation`` else ``cooldown``
    * ``repeat_status == "deescalation"`` -> ``allow`` if
      ``policy.allow_deescalation`` else ``cooldown``
    """
    if policy is None:
        policy = DEFAULT_CR_COOLDOWN_POLICY

    if repeat_preview is None:
        return CRCooldownDecision(
            event_key=event_key,
            action=ACTION_NOT_EVALUATED,
            reason="no repeat preview supplied",
        )

    status = repeat_preview.status
    base = dict(
        event_key=event_key,
        repeat_status=status,
        current_decision_level=repeat_preview.current_decision_level,
        previous_decision_level=repeat_preview.previous_decision_level,
        current_score=repeat_preview.current_score,
        previous_score=repeat_preview.previous_score,
    )

    # Fail-closed: a repeat preview built for a different event must never
    # produce an allow/cooldown verdict for this event. Decline instead.
    if repeat_preview.event_key != event_key:
        return CRCooldownDecision(
            action=ACTION_NOT_EVALUATED,
            reason="repeat preview event key does not match current event key",
            **base,
        )

    if status == "not_evaluated":
        return CRCooldownDecision(
            action=ACTION_NOT_EVALUATED,
            reason="repeat preview was not evaluated",
            **base,
        )

    if status == "new":
        if policy.allow_new_events:
            return CRCooldownDecision(
                action=ACTION_ALLOW_NEW,
                reason="new event is allowed by cooldown policy",
                **base,
            )
        return CRCooldownDecision(
            action=ACTION_COOLDOWN,
            reason="new events are disabled by cooldown policy",
            cooldown_minutes=policy.same_level_cooldown_minutes,
            **base,
        )

    if status == "same_level_repeat":
        return CRCooldownDecision(
            action=ACTION_COOLDOWN,
            reason="same-level repeat is inside cooldown policy",
            cooldown_minutes=policy.same_level_cooldown_minutes,
            **base,
        )

    if status == "same_event_repeat":
        return CRCooldownDecision(
            action=ACTION_COOLDOWN,
            reason="same-event repeat is inside cooldown policy",
            cooldown_minutes=policy.same_level_cooldown_minutes,
            **base,
        )

    if status == "meaningful_escalation":
        if policy.allow_meaningful_escalation:
            return CRCooldownDecision(
                action=ACTION_ALLOW_ESCALATION,
                reason="meaningful escalation bypasses cooldown preview",
                **base,
            )
        return CRCooldownDecision(
            action=ACTION_COOLDOWN,
            reason="meaningful escalation is disabled by cooldown policy",
            cooldown_minutes=policy.same_level_cooldown_minutes,
            **base,
        )

    if status == "deescalation":
        if policy.allow_deescalation:
            return CRCooldownDecision(
                action=ACTION_ALLOW,
                reason="deescalation is allowed by cooldown policy",
                **base,
            )
        return CRCooldownDecision(
            action=ACTION_COOLDOWN,
            reason="deescalation cools down by default policy",
            cooldown_minutes=policy.same_level_cooldown_minutes,
            **base,
        )

    # Unknown / unexpected status: be conservative and do not claim a verdict.
    return CRCooldownDecision(
        action=ACTION_NOT_EVALUATED,
        reason="unrecognized repeat status",
        **base,
    )


# ---------------------------------------------------------------------------
# Batch helper
# ---------------------------------------------------------------------------


def decide_cr_cooldowns(
    previews: tuple[CRRepeatPreview, ...],
    *,
    policy: CRCooldownPolicy | None = None,
) -> tuple[CRCooldownDecision, ...]:
    """Decide cooldown actions for a batch while preserving input order.

    Pure: returns a new tuple, mutates nothing, and has no side effects.
    """
    decisions: list[CRCooldownDecision] = []
    for preview in previews:
        decisions.append(
            decide_cr_cooldown(
                event_key=preview.event_key,
                repeat_preview=preview,
                policy=policy,
            )
        )
    return tuple(decisions)
