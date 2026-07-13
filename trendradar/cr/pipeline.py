# coding=utf-8
"""
CR offline pipeline assembly (PR9j).

Composes existing CR layers (clustering → scoring → decision → presentation
→ Markdown / HTML audit → artifact writing) into a single pure pipeline.

Purely internal — does NOT integrate with runtime, messaging, notification,
storage, config, report/archive modules, or AI analysis models.

Design reference: PR9j.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from trendradar.cr.artifacts import (
    CRArtifactConfig,
    CRArtifactPaths,
    write_cr_artifact_bundle,
)
from trendradar.cr.cluster import build_cr_candidates
from trendradar.cr.decision import (
    CRDecision,
    CRDecisionPolicy,
    DEFAULT_CR_URGENT_THRESHOLD,
    DECISION_ALERT,
    DECISION_URGENT,
    count_high_score_suppressed,
    decide_cr_candidates,
)
from trendradar.cr.html import CRHTMLRenderConfig, render_cr_html_audit
from trendradar.cr.markdown import (
    CRMarkdownRenderConfig,
    render_cr_markdown_audit,
)
from trendradar.cr.models import (
    CRCandidate,
    CRClusterConfig,
    CRPrimitiveRecord,
)
from trendradar.cr.input_health import (
    CRInputHealth,
    collection_coverage_summary,
)
from trendradar.cr.presentation import (
    CRPresentedCandidate,
    CRPresentationRun,
    CRTextPresentationConfig,
    bind_cr_presented_candidates,
    count_cr_a_eligible,
    render_cr_a_text,
    select_cr_a_candidates,
    sort_cr_presented_candidates,
)
from trendradar.cr.scoring import (
    CRScoringProfile,
    CRScoreResult,
    score_cr_candidate,
)


# ---------------------------------------------------------------------------
# Pipeline config models
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class CRPipelineRenderConfig:
    """Render sub-configs for the pipeline."""

    text: CRTextPresentationConfig | None = None
    markdown: CRMarkdownRenderConfig | None = None
    html: CRHTMLRenderConfig | None = None


@dataclass(frozen=True)
class CRPipelineConfig:
    """Pipeline-level configuration.

    ``None`` for any sub-config means the lower-layer default is used.
    """

    cluster: CRClusterConfig | None = None
    scoring: CRScoringProfile | None = None
    decision: CRDecisionPolicy | None = None
    render: CRPipelineRenderConfig = field(default_factory=CRPipelineRenderConfig)


# ---------------------------------------------------------------------------
# Pipeline result models
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class CRPipelineResult:
    """Full result of the CR offline pipeline."""

    run_label: str
    primitives: tuple[CRPrimitiveRecord, ...]
    candidates: tuple[CRCandidate, ...]
    score_results: tuple[CRScoreResult, ...]
    decisions: tuple[CRDecision, ...]
    presented_candidates: tuple[CRPresentedCandidate, ...]
    cr_a_candidates: tuple[CRPresentedCandidate, ...]
    cr_a_text: str
    markdown_audit_text: str
    html_audit_text: str
    high_score_suppressed_count: int
    coverage_warning: str | None = None


@dataclass(frozen=True)
class CRPipelineArtifactResult:
    """Pipeline result together with artifact paths."""

    pipeline: CRPipelineResult
    artifact_paths: CRArtifactPaths


# ---------------------------------------------------------------------------
# Main pure pipeline function
# ---------------------------------------------------------------------------


def build_cr_pipeline_from_primitives(
    primitives: list[CRPrimitiveRecord] | tuple[CRPrimitiveRecord, ...],
    *,
    run_label: str,
    config: CRPipelineConfig | None = None,
    urgent_threshold: float = DEFAULT_CR_URGENT_THRESHOLD,
    input_health: CRInputHealth | None = None,
) -> CRPipelineResult:
    """Build the full CR offline pipeline from primitive records.

    Composes: clustering → scoring → decision → presentation → rendering.
    Pure — does NOT write files or call runtime/messaging/storage.

    Parameters
    ----------
    primitives:
        Adapter-level primitive records (output of adapt_hotlist_stats /
        adapt_rss_stats).
    run_label:
        Human-readable run label (e.g. ``"2026-06-10 09:00"``).
    config:
        Pipeline config.  Uses lower-layer defaults when ``None``.
    urgent_threshold:
        Score threshold for counting high-score suppressed candidates.

    Returns
    -------
    CRPipelineResult
    """
    if config is None:
        config = CRPipelineConfig()

    render_cfg = config.render

    # 1. Convert primitives to tuple.
    primitives_tuple = tuple(primitives)

    # 2. Cluster.
    candidates = build_cr_candidates(
        primitives_tuple, config=config.cluster
    )

    # 2b. Corroboration mode: drop cross-evidence-admitted RSS candidates that
    # never merged into a hotlist event.  Legacy keyword RSS has no admission
    # marker and retains its pre-funnel behavior.
    drop_unmerged_rss = (
        config.cluster.drop_unmerged_rss if config.cluster is not None else False
    )
    if drop_unmerged_rss:
        candidates = [
            c
            for c in candidates
            if not (
                c.primary_source_type == "rss"
                and c.source_items
                and all(item.cross_evidence_admitted for item in c.source_items)
            )
        ]

    # 3. Score.
    score_results = [
        score_cr_candidate(
            c,
            profile=config.scoring,
            input_health=input_health,
        )
        for c in candidates
    ]

    # 4. Decide.
    decisions = decide_cr_candidates(
        score_results, policy=config.decision
    )

    # 5. Bind.
    presented = bind_cr_presented_candidates(
        candidates, score_results, decisions
    )
    presented_sorted = sort_cr_presented_candidates(presented)

    # 6. Select CR-A candidates.
    cr_a = select_cr_a_candidates(
        presented_sorted, config=render_cfg.text
    )

    # Count eligible before cap for truncation hint in the dispatch header.
    cr_a_eligible_count = count_cr_a_eligible(presented_sorted)

    # Count high-score candidates suppressed by the decision layer so the
    # operator-facing dispatch can distinguish filtering from no activity.
    high_score_suppressed_count = count_high_score_suppressed(
        decisions, urgent_threshold=urgent_threshold
    )
    coverage_warning = (
        collection_coverage_summary(input_health)["warning"]
        if input_health is not None
        else None
    )

    # 7. Render CR-A text.
    run = CRPresentationRun(
        run_label=run_label,
        candidates=list(cr_a),
        high_score_suppressed_count=high_score_suppressed_count,
        coverage_warning=coverage_warning,
        total_eligible_count=cr_a_eligible_count,
    )
    cr_a_text = render_cr_a_text(run, config=render_cfg.text)

    # 8. Render Markdown audit (all presented candidates).
    markdown_audit_text = render_cr_markdown_audit(
        presented_sorted,
        run_label=run_label,
        config=render_cfg.markdown,
        urgent_threshold=urgent_threshold,
    )

    # 9. Render HTML audit (all presented candidates).
    html_audit_text = render_cr_html_audit(
        presented_sorted,
        run_label=run_label,
        config=render_cfg.html,
        urgent_threshold=urgent_threshold,
    )

    # 10. Return.
    return CRPipelineResult(
        run_label=run_label,
        primitives=primitives_tuple,
        candidates=tuple(candidates),
        score_results=tuple(score_results),
        decisions=tuple(decisions),
        presented_candidates=tuple(presented_sorted),
        cr_a_candidates=tuple(cr_a),
        cr_a_text=cr_a_text,
        markdown_audit_text=markdown_audit_text,
        html_audit_text=html_audit_text,
        high_score_suppressed_count=high_score_suppressed_count,
        coverage_warning=coverage_warning,
    )


# ---------------------------------------------------------------------------
# Artifact write helpers
# ---------------------------------------------------------------------------


def write_cr_pipeline_artifacts(
    result: CRPipelineResult,
    *,
    artifact_config: CRArtifactConfig | None = None,
) -> CRArtifactPaths:
    """Write pipeline Markdown and HTML audit artifacts.

    Delegates entirely to :func:`write_cr_artifact_bundle`.  Does NOT
    write CR-A text.
    """
    return write_cr_artifact_bundle(
        markdown_text=result.markdown_audit_text,
        html_text=result.html_audit_text,
        run_label=result.run_label,
        config=artifact_config,
    )


def build_and_write_cr_pipeline_from_primitives(
    primitives: list[CRPrimitiveRecord] | tuple[CRPrimitiveRecord, ...],
    *,
    run_label: str,
    config: CRPipelineConfig | None = None,
    artifact_config: CRArtifactConfig | None = None,
    urgent_threshold: float = DEFAULT_CR_URGENT_THRESHOLD,
) -> CRPipelineArtifactResult:
    """Build pipeline then write artifacts in one call.

    Combines :func:`build_cr_pipeline_from_primitives` and
    :func:`write_cr_pipeline_artifacts`.
    """
    pipeline_result = build_cr_pipeline_from_primitives(
        primitives,
        run_label=run_label,
        config=config,
        urgent_threshold=urgent_threshold,
    )
    paths = write_cr_pipeline_artifacts(
        pipeline_result, artifact_config=artifact_config
    )
    return CRPipelineArtifactResult(
        pipeline=pipeline_result,
        artifact_paths=paths,
    )
