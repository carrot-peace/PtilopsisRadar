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
    RANK_SENTINELS,
    is_visible_rank,
)
from trendradar.cr.adapter import (
    adapt_hotlist_stats,
    adapt_rss_stats,
)

__all__ = [
    "CRSourceItem",
    "CRPrimitiveRecord",
    "CRRunContext",
    "RANK_SENTINELS",
    "is_visible_rank",
    "adapt_hotlist_stats",
    "adapt_rss_stats",
]
