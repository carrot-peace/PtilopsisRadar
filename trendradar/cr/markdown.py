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

from trendradar.cr.decision import (
    DECISION_ALERT,
    DECISION_SUPPRESS,
    DECISION_URGENT,
    DECISION_WATCH,
)
from trendradar.cr.models import CRSourceItem
from trendradar.cr.presentation import (
    CRPresentedCandidate,
    sort_cr_presented_candidates,
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
        lines.append(f"   - {label}: {value}")

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
    lines.append(f"# {config.title}")
    lines.append("")
    lines.append(f"Run: {run_label}")
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
            lines.append(f"Candidate ID: {pc.candidate_id}")
            lines.append(f"Cluster Key: {pc.cluster_key}")
            lines.append(f"Decision: {pc.decision_level}")
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
