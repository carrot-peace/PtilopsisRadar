# coding=utf-8
"""
CR-A cooldown audit assembly (PR10e).

Pure, deterministic assembly of the existing PR10a/b/c/d primitives into a
single audit-only context, so artifacts and future *audit-only* dry-runs can
show, per candidate:

  * event identity (PR10a)
  * repeat preview against prior state (PR10b)
  * cooldown policy preview (PR10d)
  * a *proposed* next-state entry (PR10c)

This module is observability-only and intentionally inert. It does NOT enforce
cooldown, does NOT suppress dispatch, does NOT read or write state files, does
NOT touch Telegram, and does NOT integrate runtime/config. The proposed
state-update entries are computed in memory only and are never written anywhere
here.

It is pure:

  * no filesystem
  * no network
  * no environment
  * no Telegram
  * no dispatch
  * no runtime
  * no config
  * no current time read
  * no randomness

Timestamps may be supplied explicitly as strings (``seen_at``); none are
generated internally.
"""

from __future__ import annotations

from dataclasses import dataclass

from trendradar.cr.cooldown_policy import (
    CRCooldownDecision,
    CRCooldownPolicy,
    decide_cr_cooldown,
)
from trendradar.cr.event_identity import (
    CREventIdentity,
    build_cr_event_identity_from_candidate,
)
from trendradar.cr.presentation import CRPresentedCandidate
from trendradar.cr.repeat_preview import (
    CRRepeatPreview,
    CRSeenEventState,
    preview_cr_repeat,
)
from trendradar.cr.state_snapshot import (
    CREventStateEntry,
    CREventStateSnapshot,
    build_cr_event_state_entry_from_presented_candidate,
    cr_event_state_snapshot_to_seen_states,
)


# ---------------------------------------------------------------------------
# Assembled audit objects
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class CRCooldownAuditCandidate:
    """Assembled audit evidence for one presented candidate.

    ``state_update`` is a *proposed* next-state entry only. It is never
    written; persistence (if ever) belongs to a later, explicitly gated PR.
    """

    candidate_id: str
    event_identity: CREventIdentity
    repeat_preview: CRRepeatPreview
    cooldown_decision: CRCooldownDecision
    state_update: CREventStateEntry


@dataclass(frozen=True)
class CRCooldownAuditContext:
    """Run-level audit context combining all per-candidate evidence.

    ``seen_event_states`` is the prior state converted to the in-memory shape
    that the Markdown/HTML render configs already accept, so callers can render
    repeat-preview / cooldown-preview evidence without re-deriving it.

    ``state_updates`` holds the proposed next-state entries in input order;
    they are not written anywhere.
    """

    candidates: tuple[CRCooldownAuditCandidate, ...]
    seen_event_states: dict[str, CRSeenEventState]
    state_updates: tuple[CREventStateEntry, ...]


# ---------------------------------------------------------------------------
# Assembly
# ---------------------------------------------------------------------------


def build_cr_cooldown_audit_context(
    candidates: tuple[CRPresentedCandidate, ...],
    *,
    prior_snapshot: CREventStateSnapshot | None = None,
    policy: CRCooldownPolicy | None = None,
    seen_at: str | None = None,
) -> CRCooldownAuditContext:
    """Assemble an audit-only cooldown context for ``candidates``.

    Pure: preserves input order, mutates nothing, performs no I/O, reads no
    clock, and enforces no policy. Every input candidate yields exactly one
    audit candidate (no candidate is dropped or suppressed).

    Semantics
    ---------
    * ``prior_snapshot is None`` -> repeat preview is ``not_evaluated`` and the
      cooldown decision is ``not_evaluated``; ``seen_event_states`` is empty.
    * ``prior_snapshot`` provided -> it is converted to ``seen_event_states``,
      each candidate's repeat preview is built against it, and each repeat
      preview is mapped to a cooldown decision under ``policy``.

    A *proposed* next-state entry is built for every candidate using the
    explicit ``seen_at`` string (no timestamp is generated here).
    """
    snapshot_provided = prior_snapshot is not None
    seen_event_states: dict[str, CRSeenEventState] = (
        cr_event_state_snapshot_to_seen_states(prior_snapshot)
        if prior_snapshot is not None
        else {}
    )

    audit_candidates: list[CRCooldownAuditCandidate] = []
    state_updates: list[CREventStateEntry] = []

    for pc in candidates:
        identity = build_cr_event_identity_from_candidate(pc.candidate)

        seen_state = (
            seen_event_states.get(identity.event_key)
            if snapshot_provided
            else None
        )

        preview = preview_cr_repeat(
            event_key=identity.event_key,
            current_decision_level=pc.decision_level,
            current_score=pc.total_score,
            seen_state=seen_state,
            prior_state_snapshot_provided=snapshot_provided,
        )

        decision = decide_cr_cooldown(
            event_key=identity.event_key,
            repeat_preview=preview,
            policy=policy,
        )

        state_update = build_cr_event_state_entry_from_presented_candidate(
            pc,
            seen_at=seen_at,
        )

        audit_candidates.append(
            CRCooldownAuditCandidate(
                candidate_id=pc.candidate_id,
                event_identity=identity,
                repeat_preview=preview,
                cooldown_decision=decision,
                state_update=state_update,
            )
        )
        state_updates.append(state_update)

    return CRCooldownAuditContext(
        candidates=tuple(audit_candidates),
        seen_event_states=seen_event_states,
        state_updates=tuple(state_updates),
    )
