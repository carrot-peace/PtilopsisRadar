# coding=utf-8
"""
CR Markdown audit renderer.

Renders all presented candidates into a detailed Markdown audit document.
Includes every decision level (urgent / alert / watch / suppress) without
filtering.  Purely internal — does NOT implement delivery, Telegram, report,
archive, cooldown, dedupe, alert_state, runtime, or file writing.

Design reference: PR9g.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping

from trendradar.cr.decision import (
    DECISION_ALERT,
    DECISION_SUPPRESS,
    DECISION_URGENT,
    DECISION_WATCH,
)
from trendradar.cr.cooldown_policy import (
    CRCooldownDecision,
    CRCooldownPolicy,
    decide_cr_cooldown,
)
from trendradar.cr.event_identity import build_cr_event_identity_from_candidate
from trendradar.cr.models import CRSourceItem
from trendradar.cr.presentation import (
    CRPresentedCandidate,
    sort_cr_presented_candidates,
)
from trendradar.cr.repeat_preview import (
    CRRepeatPreview,
    CRSeenEventState,
    preview_cr_repeat,
)
from trendradar.cr.scoring import CRScoreResult


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class CRMarkdownRenderConfig:
    """Configuration for CR Markdown audit rendering."""

    title: str = "Ptilopsis Radar｜CR Markdown Audit"
    include_debug: bool = True
    include_source_items: bool = True
    include_score_components: bool = True
    include_event_identity: bool = True
    include_repeat_preview: bool = False
    seen_event_states: Mapping[str, CRSeenEventState] | None = None
    include_cooldown_decision: bool = False
    cooldown_policy: CRCooldownPolicy | None = None


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------

_SECTION_ORDER: list[str] = [
    DECISION_URGENT,
    DECISION_ALERT,
    DECISION_WATCH,
    DECISION_SUPPRESS,
]

_COMPONENT_ORDER: list[str] = [
    "growth_raw",
    "current_heat_raw",
    "heat",
    "cross_layer_raw",
    "background_support_raw",
    "cross_evidence",
]

_COMPONENT_DISPLAY: dict[str, str] = {
    "growth_raw": "Growth Raw",
    "current_heat_raw": "Current Heat Raw",
    "heat": "Heat",
    "cross_layer_raw": "Cross Layer Raw",
    "background_support_raw": "Background Support Raw",
    "cross_evidence": "Cross Evidence",
}

_SOURCE_ITEM_FIELDS: list[tuple[str, str]] = [
    ("source_type", "Source Type"),
    ("source_name", "Source Name"),
    ("source_id", "Source ID"),
    ("feed_id", "Feed ID"),
    ("current_rank", "Current Rank"),
    ("normalized_rank", "Normalized Rank"),
    ("is_new", "Is New"),
    ("is_new_semantics", "Is New Semantics"),
    ("first_time", "First Time"),
    ("last_time", "Last Time"),
    ("published_at", "Published At"),
]


def _escape_markdown_text(text: str) -> str:
    """Escape text for safe Markdown rendering.

    - Replaces newlines with spaces.
    - Strips surrounding whitespace.
    - Replaces ``|`` with ``\\|`` to avoid breaking tables.
    """
    return text.replace("\n", " ").strip().replace("|", "\\|")


def _format_field_value(value: object) -> str:
    """Format a metadata field value for Markdown output.

    String values are escaped via :func:`_escape_markdown_text` so that
    metadata containing ``|`` or newlines cannot pollute the audit output.
    Non-string values (ints, bools, ...) are rendered with ``str()``.
    """
    if isinstance(value, str):
        return _escape_markdown_text(value)
    return str(value)


def _format_score(v: float) -> str:
    """Format a score value to one decimal place."""
    return f"{v:.1f}"


def _render_score_components_table(sr: CRScoreResult) -> list[str]:
    """Render the score components Markdown table."""
    lines: list[str] = []
    lines.append("#### Score Components")
    lines.append("")
    lines.append("| Component | Raw | Capped | Cap |")
    lines.append("|---|---:|---:|---:|")

    for name in _COMPONENT_ORDER:
        cs = getattr(sr, name, None)
        if cs is None:
            continue
        display = _COMPONENT_DISPLAY.get(name, name)
        lines.append(
            f"| {display} "
            f"| {_format_score(cs.raw_score)} "
            f"| {_format_score(cs.capped_score)} "
            f"| {_format_score(cs.cap)} |"
        )

    return lines


def _render_source_item(item: CRSourceItem, index: int) -> list[str]:
    """Render one source item as a Markdown list entry."""
    lines: list[str] = []

    # Title line with optional link.
    title = item.title or "(untitled)"
    if item.url:
        lines.append(f"{index}. [{_escape_markdown_text(title)}]({item.url})")
    else:
        lines.append(f"{index}. {_escape_markdown_text(title)}")

    # Metadata fields — skip None / empty.
    for attr, label in _SOURCE_ITEM_FIELDS:
        value = getattr(item, attr, None)
        if value is None:
            continue
        if isinstance(value, str) and value == "":
            continue
        lines.append(f"   - {label}: {_format_field_value(value)}")

    return lines


def _render_debug(pc: CRPresentedCandidate) -> list[str]:
    """Render a minimal debug section as a fenced code block."""
    lines: list[str] = []
    lines.append("#### Debug")
    lines.append("")
    lines.append("```text")

    # Score debug — top-level keys only.
    sr_debug = pc.score_result.debug
    if sr_debug:
        for k, v in sr_debug.items():
            if isinstance(v, (str, int, float, bool)):
                lines.append(f"score.{k}: {v}")

    # Decision debug — top-level keys only.
    dec_debug = pc.decision.debug
    if dec_debug:
        for k, v in dec_debug.items():
            if isinstance(v, (str, int, float, bool)):
                lines.append(f"decision.{k}: {v}")

    lines.append("```")
    return lines


def _render_event_identity(pc: CRPresentedCandidate) -> list[str]:
    """Render audit-only event identity evidence for one candidate.

    Observability only: this evidence exists so future PR10b/c work can ask
    "is this the same event as before, and did it merely repeat or escalate?"
    It does NOT enforce dedupe or cooldown and does NOT affect dispatch.

    The raw, verbose ``cluster_key`` is intentionally NOT emitted here — only
    its short fingerprint — to keep the section readable.
    """
    identity = build_cr_event_identity_from_candidate(pc.candidate)
    lines: list[str] = []
    lines.append("#### Event Identity")
    lines.append("")
    lines.append(
        "_Identity evidence for future dedupe/cooldown (PR10b/c); "
        "not enforced here._"
    )
    lines.append("")
    lines.append(f"- Event Key: `{_escape_markdown_text(identity.event_key)}`")
    lines.append(f"- Key Basis: {_escape_markdown_text(identity.key_basis)}")
    lines.append(
        f"- Normalized Title: {_escape_markdown_text(identity.normalized_title)}"
    )
    if identity.candidate_id:
        lines.append(
            f"- Candidate ID (evidence): "
            f"{_escape_markdown_text(identity.candidate_id)}"
        )
    if identity.cluster_key_fingerprint:
        lines.append(
            f"- Cluster Key Fingerprint (evidence): "
            f"`{_escape_markdown_text(identity.cluster_key_fingerprint)}`"
        )
    lines.append(
        f"- Title Fingerprint: `{_escape_markdown_text(identity.title_fingerprint)}`"
    )
    lines.append(
        f"- Platform Fingerprint: "
        f"`{_escape_markdown_text(identity.platform_fingerprint)}`"
    )
    lines.append(
        f"- Source Fingerprint: "
        f"`{_escape_markdown_text(identity.source_fingerprint)}`"
    )
    return lines


def _render_repeat_preview(preview: CRRepeatPreview) -> list[str]:
    """Render audit-only repeat preview evidence for one candidate."""
    lines: list[str] = []
    lines.append("#### Repeat Preview")
    lines.append("")
    lines.append(f"- Status: `{_escape_markdown_text(preview.status)}`")
    if preview.reason:
        lines.append(f"- Reason: {_escape_markdown_text(preview.reason)}")
    has_prior_detail = preview.previous_decision_level is not None
    if preview.previous_decision_level is not None:
        lines.append(
            f"- Previous Level: "
            f"`{_escape_markdown_text(preview.previous_decision_level)}`"
        )
    if has_prior_detail and preview.current_decision_level is not None:
        lines.append(
            f"- Current Level: "
            f"`{_escape_markdown_text(preview.current_decision_level)}`"
        )
    if preview.previous_score is not None:
        lines.append(f"- Previous Score: `{_format_score(preview.previous_score)}`")
    if preview.previous_score is not None and preview.current_score is not None:
        lines.append(f"- Current Score: `{_format_score(preview.current_score)}`")
    if preview.previous_seen_at:
        lines.append(
            f"- Previous Seen At: "
            f"`{_escape_markdown_text(preview.previous_seen_at)}`"
        )
    return lines


def _render_cooldown_decision(decision: CRCooldownDecision) -> list[str]:
    """Render audit-only cooldown policy preview for one candidate.

    This is a preview of what a cooldown policy *would* decide. It does NOT
    enforce cooldown, suppress dispatch, or change Telegram output.
    """
    lines: list[str] = []
    lines.append("#### Cooldown Policy Preview")
    lines.append("")
    lines.append(f"- Action: `{_escape_markdown_text(decision.action)}`")
    if decision.reason:
        lines.append(f"- Reason: {_escape_markdown_text(decision.reason)}")
    if decision.repeat_status is not None:
        lines.append(
            f"- Repeat Status: `{_escape_markdown_text(decision.repeat_status)}`"
        )
    if decision.cooldown_minutes is not None:
        lines.append(f"- Cooldown Minutes: `{decision.cooldown_minutes}`")
    return lines


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def render_cr_markdown_audit(
    candidates: list[CRPresentedCandidate],
    *,
    run_label: str,
    config: CRMarkdownRenderConfig | None = None,
    urgent_threshold: float = 80.0,
) -> str:
    """Render all presented candidates as a Markdown audit document.

    Includes every decision level (urgent / alert / watch / suppress) without
    filtering.  Does NOT re-score, re-decide, filter, or write files.

    Parameters
    ----------
    candidates:
        All presented candidates — not just CR-A selected ones.
    run_label:
        Human-readable run label (e.g. ``"2026-06-09 23:30"``).
    config:
        Rendering config.  Defaults to ``CRMarkdownRenderConfig()``.
    urgent_threshold:
        Score threshold for counting high-score suppressed candidates.
        Defaults to 80.0.

    Returns
    -------
    str
        Markdown audit text.
    """
    if config is None:
        config = CRMarkdownRenderConfig()

    # Sort using existing PR9f sort (returns new list, does not mutate).
    sorted_candidates = sort_cr_presented_candidates(candidates)

    # High-score suppressed count.
    high_score_suppressed = sum(
        1
        for pc in sorted_candidates
        if pc.decision_level == DECISION_SUPPRESS
        and pc.total_score >= urgent_threshold
    )

    # Group by level.
    by_level: dict[str, list[CRPresentedCandidate]] = {lv: [] for lv in _SECTION_ORDER}
    for pc in sorted_candidates:
        if pc.decision_level in by_level:
            by_level[pc.decision_level].append(pc)

    lines: list[str] = []

    # --- Header ---
    lines.append(f"# {_escape_markdown_text(config.title)}")
    lines.append("")
    lines.append(f"Run: {_escape_markdown_text(run_label)}")
    lines.append(f"Candidates: {len(sorted_candidates)}")
    lines.append(f"High-score suppressed candidates: {high_score_suppressed}")

    # --- Sections ---
    for level in _SECTION_ORDER:
        lines.append("")
        lines.append(f"## {level}")
        lines.append("")

        section_candidates = by_level[level]
        if not section_candidates:
            lines.append("_No candidates._")
            continue

        for idx, pc in enumerate(section_candidates, start=1):
            lines.append(f"### {idx}. {_escape_markdown_text(pc.display_title)}")
            lines.append("")
            lines.append(f"Candidate ID: {_escape_markdown_text(pc.candidate_id)}")
            lines.append(f"Cluster Key: {_escape_markdown_text(pc.cluster_key)}")
            lines.append(f"Decision: {_escape_markdown_text(pc.decision_level)}")
            lines.append(f"Total Score: {_format_score(pc.total_score)}")

            # Triggers.
            if pc.trigger_reasons:
                lines.append(
                    f"Triggers: {'; '.join(_escape_markdown_text(r) for r in pc.trigger_reasons)}"
                )
            else:
                lines.append("Triggers: score threshold")

            # Suppress labels.
            if pc.suppress_labels:
                lines.append(
                    f"Suppress Labels: {'; '.join(_escape_markdown_text(l) for l in pc.suppress_labels)}"
                )

            # Link.
            if pc.representative_url:
                lines.append(f"Link: {pc.representative_url}")

            # Event identity evidence (audit-only; no enforcement).
            if config.include_event_identity:
                lines.append("")
                lines.extend(_render_event_identity(pc))

            # Repeat preview evidence (audit-only; no enforcement).
            if config.include_repeat_preview:
                identity = build_cr_event_identity_from_candidate(pc.candidate)
                seen_state = (
                    config.seen_event_states.get(identity.event_key)
                    if config.seen_event_states is not None
                    else None
                )
                preview = preview_cr_repeat(
                    event_key=identity.event_key,
                    current_decision_level=pc.decision_level,
                    current_score=pc.total_score,
                    seen_state=seen_state,
                    prior_state_snapshot_provided=(
                        config.seen_event_states is not None
                    ),
                )
                lines.append("")
                lines.extend(_render_repeat_preview(preview))

                # Cooldown policy preview (audit-only; no enforcement). Gated
                # on repeat preview being enabled so a preview already exists.
                if config.include_cooldown_decision:
                    decision = decide_cr_cooldown(
                        event_key=identity.event_key,
                        repeat_preview=preview,
                        policy=config.cooldown_policy,
                    )
                    lines.append("")
                    lines.extend(_render_cooldown_decision(decision))

            # Score components.
            if config.include_score_components:
                lines.append("")
                lines.extend(_render_score_components_table(pc.score_result))

            # Source items.
            if config.include_source_items and pc.candidate.source_items:
                lines.append("")
                lines.append("#### Source Items")
                lines.append("")
                for si_idx, item in enumerate(pc.candidate.source_items, start=1):
                    lines.extend(_render_source_item(item, si_idx))

            # Debug.
            if config.include_debug:
                lines.append("")
                lines.extend(_render_debug(pc))

    return "\n".join(lines)
