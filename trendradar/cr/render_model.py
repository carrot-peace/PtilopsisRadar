"""Typed, precomputed view model for pure CR audit rendering."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Sequence

from trendradar.cr.cooldown_policy import (
    CRCooldownDecision,
    CRCooldownPolicy,
    decide_cr_cooldown,
)
from trendradar.cr.decision import (
    DECISION_ALERT,
    DECISION_SUPPRESS,
    DECISION_URGENT,
    DECISION_WATCH,
)
from trendradar.cr.event_identity import (
    CREventIdentity,
    build_cr_event_identity_from_candidate,
)
from trendradar.cr.input_health import (
    CRInputHealth,
    input_health_to_json_dict,
)
from trendradar.cr.presentation import (
    CRPresentedCandidate,
    sort_cr_presented_candidates,
)
from trendradar.cr.repeat_preview import (
    CRRepeatPreview,
    CRSeenEventState,
    preview_cr_repeat,
)
from trendradar.cr.state_transition_preview import (
    CREventStateTransitionPreview,
)


CR_RENDER_SECTION_ORDER = (
    DECISION_URGENT,
    DECISION_ALERT,
    DECISION_WATCH,
    DECISION_SUPPRESS,
)


@dataclass(frozen=True, slots=True)
class CRCandidateRenderView:
    """One presented candidate with all optional evidence precomputed."""

    presented: CRPresentedCandidate
    identity: CREventIdentity | None = None
    repeat_preview: CRRepeatPreview | None = None
    cooldown_decision: CRCooldownDecision | None = None


@dataclass(frozen=True, slots=True)
class CRRenderSection:
    """Typed candidates for one decision-level section."""

    level: str
    candidates: tuple[CRCandidateRenderView, ...]


@dataclass(frozen=True, slots=True)
class CRAuditRenderModel:
    """Complete immutable input consumed by Markdown and HTML renderers."""

    run_label: str
    candidates: tuple[CRCandidateRenderView, ...]
    sections: tuple[CRRenderSection, ...]
    high_score_suppressed_count: int
    input_health: Mapping[str, Any] | None = None
    state_transition_preview: CREventStateTransitionPreview | None = None


def build_cr_audit_render_model(
    candidates: Sequence[CRPresentedCandidate],
    *,
    run_label: str,
    urgent_threshold: float = 80.0,
    include_event_identity: bool = True,
    include_repeat_preview: bool = False,
    seen_event_states: Mapping[str, CRSeenEventState] | None = None,
    include_cooldown_decision: bool = False,
    cooldown_policy: CRCooldownPolicy | None = None,
    input_health: CRInputHealth | None = None,
    state_transition_preview: CREventStateTransitionPreview | None = None,
) -> CRAuditRenderModel:
    """Precompute domain evidence once before any output formatting."""
    sorted_candidates = sort_cr_presented_candidates(list(candidates))
    views: list[CRCandidateRenderView] = []
    need_identity = include_event_identity or include_repeat_preview

    for presented in sorted_candidates:
        identity = (
            build_cr_event_identity_from_candidate(presented.candidate)
            if need_identity
            else None
        )
        repeat_preview = None
        cooldown_decision = None
        if include_repeat_preview and identity is not None:
            seen_state = (
                seen_event_states.get(identity.event_key)
                if seen_event_states is not None
                else None
            )
            repeat_preview = preview_cr_repeat(
                event_key=identity.event_key,
                current_decision_level=presented.decision_level,
                current_score=presented.total_score,
                seen_state=seen_state,
                prior_state_snapshot_provided=(
                    seen_event_states is not None
                ),
            )
            if include_cooldown_decision:
                cooldown_decision = decide_cr_cooldown(
                    event_key=identity.event_key,
                    repeat_preview=repeat_preview,
                    policy=cooldown_policy,
                )
        views.append(
            CRCandidateRenderView(
                presented=presented,
                identity=identity,
                repeat_preview=repeat_preview,
                cooldown_decision=cooldown_decision,
            )
        )

    sections = tuple(
        CRRenderSection(
            level=level,
            candidates=tuple(
                view
                for view in views
                if view.presented.decision_level == level
            ),
        )
        for level in CR_RENDER_SECTION_ORDER
    )
    return CRAuditRenderModel(
        run_label=run_label,
        candidates=tuple(views),
        sections=sections,
        high_score_suppressed_count=sum(
            1
            for view in views
            if view.presented.decision_level == DECISION_SUPPRESS
            and view.presented.total_score >= urgent_threshold
        ),
        input_health=(
            input_health_to_json_dict(input_health)
            if input_health is not None
            else None
        ),
        state_transition_preview=state_transition_preview,
    )
