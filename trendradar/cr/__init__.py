# coding=utf-8
"""
CR (Current Report) primitive layer.

PR9b: primitive models + input adapter.
PR9c: topic clustering / true CRCandidate.
PR9d: scoring.
PR9e: decision policy.
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
]
