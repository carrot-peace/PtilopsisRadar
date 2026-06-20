# coding=utf-8
"""
CR presentation layer.

Combines CRCandidate + CRScoreResult + CRDecision into displayable objects
and renders CR-A text output.  Purely internal — does NOT implement delivery,
Telegram, report, archive, cooldown, dedupe, alert_state, or runtime.

Design reference: PR9f.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime
from typing import Literal

from trendradar.cr.cluster import normalize_topic_text
from trendradar.cr.decision import (
    CRDecision,
    CRDecisionLevel,
    DECISION_ALERT,
    DECISION_SUPPRESS,
    DECISION_URGENT,
    DECISION_WATCH,
)
from trendradar.cr.models import CRCandidate
from trendradar.cr.scoring import CRScoreResult


# ---------------------------------------------------------------------------
# Decision level sort order
# ---------------------------------------------------------------------------

_LEVEL_ORDER: dict[str, int] = {
    DECISION_URGENT: 0,
    DECISION_ALERT: 1,
    DECISION_WATCH: 2,
    DECISION_SUPPRESS: 3,
}


# ---------------------------------------------------------------------------
# CRPresentedCandidate
# ---------------------------------------------------------------------------


@dataclass
class CRPresentedCandidate:
    """Bound display object combining candidate, score, and decision."""

    candidate: CRCandidate
    score_result: CRScoreResult
    decision: CRDecision

    candidate_id: str
    cluster_key: str
    display_title: str
    representative_url: str | None
    decision_level: CRDecisionLevel
    total_score: float
    trigger_reasons: list[str] = field(default_factory=list)
    suppress_labels: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# CRPresentationRun
# ---------------------------------------------------------------------------


@dataclass
class CRPresentationRun:
    """Run-level presentation container.

    ``candidates`` contains already-selected candidates for this presentation
    output (i.e. the result of :func:`select_cr_a_candidates` or equivalent).
    The renderer renders exactly these candidates without further filtering.

    ``total_eligible_count`` is the number of push-eligible alert/urgent
    candidates before the max_candidates cap was applied.  When it exceeds
    ``len(candidates)`` the difference signals that candidates were truncated.
    Defaults to 0, which the renderer treats as "use len(candidates)".
    """

    run_label: str
    candidates: list[CRPresentedCandidate]
    high_score_suppressed_count: int = 0
    total_eligible_count: int = 0


# ---------------------------------------------------------------------------
# CRTextPresentationConfig
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class CRTextPresentationConfig:
    """Configuration for CR-A text rendering."""

    max_candidates: int = 3
    max_trigger_items: int = 3
    include_scores: bool = False
    include_links: bool = True
    title: str = "Ptilopsis Radar｜CR-A"


# ---------------------------------------------------------------------------
# Binding helper
# ---------------------------------------------------------------------------


def bind_cr_presented_candidates(
    candidates: list[CRCandidate],
    score_results: list[CRScoreResult],
    decisions: list[CRDecision],
) -> list[CRPresentedCandidate]:
    """Bind candidates, score results, and decisions by candidate_id.

    Validates consistency:
      - Every candidate must have a matching score and decision.
      - No duplicate candidate_id in scores or decisions.
      - cluster_key must match across all three.

    Preserves input order of candidates.  Does NOT sort, filter, re-score,
    or re-decide.
    """
    # Build score lookup and check for duplicates.
    score_by_id: dict[str, CRScoreResult] = {}
    for sr in score_results:
        if sr.candidate_id in score_by_id:
            raise ValueError(
                f"Duplicate score candidate_id: {sr.candidate_id!r}"
            )
        score_by_id[sr.candidate_id] = sr

    # Build decision lookup and check for duplicates.
    decision_by_id: dict[str, CRDecision] = {}
    for d in decisions:
        if d.candidate_id in decision_by_id:
            raise ValueError(
                f"Duplicate decision candidate_id: {d.candidate_id!r}"
            )
        decision_by_id[d.candidate_id] = d

    presented: list[CRPresentedCandidate] = []
    for cand in candidates:
        cid = cand.candidate_id

        sr = score_by_id.get(cid)
        if sr is None:
            raise ValueError(f"Missing score for candidate_id: {cid!r}")

        dec = decision_by_id.get(cid)
        if dec is None:
            raise ValueError(f"Missing decision for candidate_id: {cid!r}")

        # Validate cluster_key consistency.
        if sr.cluster_key != cand.cluster_key:
            raise ValueError(
                f"Score cluster_key mismatch for {cid!r}: "
                f"candidate={cand.cluster_key!r}, score={sr.cluster_key!r}"
            )
        if dec.cluster_key != cand.cluster_key:
            raise ValueError(
                f"Decision cluster_key mismatch for {cid!r}: "
                f"candidate={cand.cluster_key!r}, decision={dec.cluster_key!r}"
            )

        # Trigger reasons: prefer decision, copy list.
        trigger_reasons = (
            list(dec.trigger_reasons)
            if dec.trigger_reasons
            else list(sr.trigger_reasons)
        )

        presented.append(
            CRPresentedCandidate(
                candidate=cand,
                score_result=sr,
                decision=dec,
                candidate_id=cid,
                cluster_key=cand.cluster_key,
                display_title=cand.display_title,
                representative_url=cand.representative_url,
                decision_level=dec.level,
                total_score=dec.total_score,
                trigger_reasons=trigger_reasons,
                suppress_labels=list(dec.suppress_labels),
            )
        )

    return presented


# ---------------------------------------------------------------------------
# Sorting helper
# ---------------------------------------------------------------------------


def sort_cr_presented_candidates(
    presented: list[CRPresentedCandidate],
) -> list[CRPresentedCandidate]:
    """Sort presented candidates by level, score, title, and id.

    Order:
      1. Decision level: urgent < alert < watch < suppress.
      2. Within same level: total_score descending.
      3. Within same score: display_title normalized lexicographic.
      4. Within same title: candidate_id ascending.

    Returns a new list; does NOT mutate input.
    """

    def _sort_key(pc: CRPresentedCandidate) -> tuple:
        return (
            _LEVEL_ORDER.get(pc.decision_level, 99),
            -pc.total_score,
            normalize_topic_text(pc.display_title),
            pc.candidate_id,
        )

    return sorted(presented, key=_sort_key)


# ---------------------------------------------------------------------------
# CR-A candidate selection
# ---------------------------------------------------------------------------


def select_cr_a_candidates(
    presented: list[CRPresentedCandidate],
    *,
    config: CRTextPresentationConfig | None = None,
) -> list[CRPresentedCandidate]:
    """Select candidates eligible for CR-A text output.

    Rules:
      - Only candidates with decision.push_eligible == True.
      - Only candidates with decision_level in {alert, urgent}.
      - Sorted by sort_cr_presented_candidates().
      - Capped at config.max_candidates.

    Returns a new list; does NOT mutate input.
    """
    if config is None:
        config = CRTextPresentationConfig()

    eligible = [
        pc
        for pc in presented
        if pc.decision.push_eligible
        and pc.decision_level in (DECISION_ALERT, DECISION_URGENT)
    ]

    sorted_eligible = sort_cr_presented_candidates(eligible)
    return sorted_eligible[: config.max_candidates]


# ---------------------------------------------------------------------------
# CR-A text rendering helpers
# ---------------------------------------------------------------------------

_RUN_LABEL_RE = re.compile(r'.*?(\d{8})-(\d{6})$')
_TRIGGER_REASON_RE = re.compile(r'^(\w+)=([0-9.]+)(?:\((.+)\))?$')
_SOURCE_COUNT_RE = re.compile(r'^source_coverage_heat=[0-9.]+\(n=(\d+)\)$')


def _format_run_datetime(run_label: str) -> str:
    """Parse run_label into a human-readable datetime string.

    Handles the standard format ``{mode}-{YYYYMMDD}-{HHMMss}``.
    Falls back to the raw run_label if the pattern does not match.
    """
    m = _RUN_LABEL_RE.match(run_label)
    if not m:
        return run_label
    try:
        dt = datetime.strptime(f"{m.group(1)}{m.group(2)}", "%Y%m%d%H%M%S")
        return f"{dt:%Y-%m-%d %H:%M} UTC+8"
    except ValueError:
        return run_label


def _format_trigger_item(reason: str) -> tuple[str, float] | None:
    """Parse one raw trigger reason into (display_text, score).

    Returns None for unknown keys, unrenderable formats, or zero scores.
    """
    m = _TRIGGER_REASON_RE.match(reason)
    if not m:
        return None
    key, score_str, meta = m.group(1), m.group(2), m.group(3)
    score = float(score_str)
    if score == 0.0:
        return None

    if key == "rank_movement":
        return f"rank↑{score:.1f}", score
    if key == "new_burst":
        return f"burst+{score:.1f}", score
    if key == "recency_momentum":
        return f"momentum+{score:.1f}", score
    if key == "weak_persistence":
        return f"persist+{score:.1f}", score
    if key == "best_rank_heat" and meta:
        rank_m = re.search(r'rank=(\d+)', meta)
        if rank_m:
            return f"#{rank_m.group(1)}", score
    if key == "hotlist_rss_cooccurrence":
        return "cross", score
    return None


def _extract_source_count(reasons: list[str]) -> int:
    """Extract distinct source count from the source_coverage_heat reason."""
    for r in reasons:
        m = _SOURCE_COUNT_RE.match(r)
        if m:
            return int(m.group(1))
    return 1


def _format_trigger_summary(reasons: list[str], max_items: int = 3) -> str:
    """Format trigger reasons into a short semicolon-separated summary.

    Selects the top ``max_items`` reasons by score, appends the distinct
    source count as ``src N``.  Returns ``"score threshold"`` when no
    displayable reasons exist and reasons is empty.
    """
    if not reasons:
        return "score threshold"

    parsed: list[tuple[str, float]] = []
    for r in reasons:
        item = _format_trigger_item(r)
        if item is not None:
            parsed.append(item)

    parsed.sort(key=lambda x: x[1], reverse=True)
    parts = [text for text, _ in parsed[:max_items]]
    parts.append(f"src {_extract_source_count(reasons)}")
    return "; ".join(parts)


# ---------------------------------------------------------------------------
# CR-A text rendering
# ---------------------------------------------------------------------------

_DEFAULT_CONFIG = CRTextPresentationConfig()


def render_cr_a_text(
    run: CRPresentationRun,
    *,
    config: CRTextPresentationConfig | None = None,
) -> str:
    """Render CR-A text output from a presentation run.

    Renders exactly ``run.candidates`` — does NOT filter, select, sort,
    re-score, or re-decide.  Selection must happen before constructing
    the ``CRPresentationRun``.

    Deterministic, no emoji, English system terms.
    Does NOT fabricate summaries or show scores by default.
    """
    if config is None:
        config = _DEFAULT_CONFIG

    candidates = run.candidates
    lines: list[str] = []

    # Header.
    lines.append(config.title)
    lines.append(_format_run_datetime(run.run_label))
    eligible_count = run.total_eligible_count if run.total_eligible_count > 0 else len(candidates)
    lines.append(f"Candidates: {eligible_count}")
    lines.append("")

    if not candidates:
        lines.append("No alert candidates.")
        return "\n".join(lines)

    # Candidates.
    for idx, pc in enumerate(candidates, start=1):
        lines.append(f"{idx}. {pc.display_title}")
        lines.append(pc.decision_level)
        lines.append(_format_trigger_summary(pc.trigger_reasons, config.max_trigger_items))

        # Score (optional).
        if config.include_scores:
            lines.append(f"Score: {pc.total_score:.1f}")

        # Link (optional).
        if config.include_links and pc.representative_url:
            lines.append(f"Link: {pc.representative_url}")

        # Blank line between candidates (but not after last).
        if idx < len(candidates):
            lines.append("")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Convenience helper
# ---------------------------------------------------------------------------


def render_cr_a_text_from_parts(
    candidates: list[CRCandidate],
    score_results: list[CRScoreResult],
    decisions: list[CRDecision],
    *,
    run_label: str,
    config: CRTextPresentationConfig | None = None,
) -> str:
    """Convenience: bind → select → run → render in one call.

    Validates binding consistency (may raise ValueError).
    """
    presented = bind_cr_presented_candidates(
        candidates, score_results, decisions
    )
    eligible_total = sum(
        1 for pc in presented
        if pc.decision.push_eligible
        and pc.decision_level in (DECISION_ALERT, DECISION_URGENT)
    )
    selected = select_cr_a_candidates(presented, config=config)
    run = CRPresentationRun(
        run_label=run_label,
        candidates=selected,
        total_eligible_count=eligible_total,
    )
    return render_cr_a_text(run, config=config)
