# coding=utf-8
"""
CR (Current Report) primitive layer.

PR9b: primitive models + input adapter.
PR9c: topic clustering / true CRCandidate.
PR9d: scoring.
PR9e: decision policy.
PR9f: presentation layer.
PR9g: Markdown audit renderer.
PR9h: artifact path resolver / writer.
PR9i: canonical HTML audit renderer.
"""

from trendradar.cr.models import (
    CRSourceItem,
    CRPrimitiveRecord,
    CRRunContext,
    CRCandidate,
    CRClusterConfig,
    RANK_SENTINELS,
    is_visible_rank,
)
from trendradar.cr.adapter import (
    adapt_hotlist_stats,
    adapt_rss_stats,
)
from trendradar.cr.cluster import (
    build_cr_candidates,
)
from trendradar.cr.scoring import (
    CRScoringProfile,
    CRComponentScore,
    CRScoreResult,
    DEFAULT_CR_SCORING_PROFILE,
    clamp_score,
    make_component_score,
    score_growth_raw,
    score_current_heat_raw,
    score_cross_layer_raw,
    combine_cr_scores,
    score_cr_candidate,
)
from trendradar.cr.decision import (
    CRDecisionPolicy,
    CRDecision,
    CRDecisionLevel,
    DEFAULT_CR_DECISION_POLICY,
    apply_cr_decision,
    decide_cr_candidates,
    count_high_score_suppressed,
)
from trendradar.cr.presentation import (
    CRPresentedCandidate,
    CRPresentationRun,
    CRTextPresentationConfig,
    bind_cr_presented_candidates,
    sort_cr_presented_candidates,
    select_cr_a_candidates,
    render_cr_a_text,
    render_cr_a_text_from_parts,
)
from trendradar.cr.markdown import (
    CRMarkdownRenderConfig,
    render_cr_markdown_audit,
)
from trendradar.cr.html import (
    CRHTMLRenderConfig,
    render_cr_html_audit,
)
from trendradar.cr.artifacts import (
    CRArtifactConfig,
    CRArtifactPaths,
    sanitize_artifact_label,
    resolve_cr_artifact_paths,
    write_text_artifact,
    write_cr_artifact_bundle,
    write_cr_markdown_audit_artifact,
    write_cr_html_artifact,
    render_and_write_cr_artifacts,
)

__all__ = [
    "CRSourceItem",
    "CRPrimitiveRecord",
    "CRRunContext",
    "CRCandidate",
    "CRClusterConfig",
    "RANK_SENTINELS",
    "is_visible_rank",
    "adapt_hotlist_stats",
    "adapt_rss_stats",
    "build_cr_candidates",
    "CRScoringProfile",
    "CRComponentScore",
    "CRScoreResult",
    "DEFAULT_CR_SCORING_PROFILE",
    "clamp_score",
    "make_component_score",
    "score_growth_raw",
    "score_current_heat_raw",
    "score_cross_layer_raw",
    "combine_cr_scores",
    "score_cr_candidate",
    "CRDecisionPolicy",
    "CRDecision",
    "CRDecisionLevel",
    "DEFAULT_CR_DECISION_POLICY",
    "apply_cr_decision",
    "decide_cr_candidates",
    "count_high_score_suppressed",
    "CRPresentedCandidate",
    "CRPresentationRun",
    "CRTextPresentationConfig",
    "bind_cr_presented_candidates",
    "sort_cr_presented_candidates",
    "select_cr_a_candidates",
    "render_cr_a_text",
    "render_cr_a_text_from_parts",
    "CRMarkdownRenderConfig",
    "render_cr_markdown_audit",
    "CRHTMLRenderConfig",
    "render_cr_html_audit",
    "CRArtifactConfig",
    "CRArtifactPaths",
    "sanitize_artifact_label",
    "resolve_cr_artifact_paths",
    "write_text_artifact",
    "write_cr_artifact_bundle",
    "write_cr_markdown_audit_artifact",
    "write_cr_html_artifact",
    "render_and_write_cr_artifacts",
]
