# coding=utf-8
"""
CR cross-evidence RSS admission (funnel stage 1).

English RSS reaches CR today only through ``count_rss_frequency`` (the
Chinese-keyword gate), which English titles almost never pass — so Rule 4 has
no RSS to corroborate hotlist events with.  This module gives CR its own RSS
path: from the run's RAW RSS, admit only items that share an entity with the
current hotlist pool (plus a recency window), then hand them to the existing
``adapt_rss_stats`` adapter as a synthetic keyword group.

Intent (corroboration-only): admission is deliberately LOOSE (high recall) —
the precise same-event decision is Rule 4's job (funnel stage 2), and RSS that
never merges is dropped post-clustering (stage 3).  Volume is bounded by the
recency window, the post-clustering drop, and an optional per-topic cap.

Deterministic, zero-runtime-AI.  Reserves a seam for a future independent
English stream (see the admission branch comment below).

Design reference: plan staged-fluttering-lynx (§1-§5).
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Dict, List, Optional, Set

from trendradar.cr.entity_match import EntityResources, extract_entities


def _parse_published_at(value: Optional[str]) -> Optional[datetime]:
    """Parse an ISO published_at string; None on missing/unparseable."""
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except (ValueError, TypeError):
        return None


def _within_window(
    published_at: Optional[str], now: datetime, window_hours: float
) -> bool:
    """True when published_at is within the recency window.

    Lenient: unparseable/missing timestamps pass (raw_rss_items is already
    per-feed age-filtered upstream), so a format quirk never drops an item.
    """
    dt = _parse_published_at(published_at)
    if dt is None:
        return True
    cutoff = now - timedelta(hours=window_hours)
    # Compare in a tz-consistent way; fall back to naive if either lacks tzinfo.
    if dt.tzinfo is not None and now.tzinfo is None:
        dt = dt.replace(tzinfo=None)
    elif dt.tzinfo is None and now.tzinfo is not None:
        dt = dt.replace(tzinfo=now.tzinfo)
    return dt >= cutoff


def select_cross_evidence_rss(
    raw_rss_items: List[dict],
    hotlist_titles: List[str],
    *,
    resources: EntityResources,
    now: datetime,
    window_hours: float = 36.0,
    max_per_topic: Optional[int] = None,
) -> List[dict]:
    """Admit RSS that may corroborate a hotlist event; return rss_stats shape.

    Args:
        raw_rss_items: full RSS for the run, dicts shaped like
            ``{title, feed_id, feed_name, url, published_at, summary, author}``
            (output of ``__main__._convert_rss_items_to_list``).
        hotlist_titles: this run's hotlist titles (anchor set).
        resources: entity dictionary + stoplist (reused from entity_match).
        now: current time (for the recency window).
        window_hours: only consider RSS published within this many hours.
        max_per_topic: optional cap — per best-matching hotlist title, keep at
            most this many RSS (by entity-overlap count, desc).  None = no cap.

    Returns:
        A list with a single synthetic keyword-group dict
        ``[{"word": None, "titles": [<title-item>, ...]}]`` ready for
        :func:`trendradar.cr.adapter.adapt_rss_stats`.  Empty list when nothing
        is admitted.
    """
    # Per-hotlist-title entity sets (for admission + per-topic capping).
    hotlist_entity_sets: List[Set[str]] = [
        extract_entities(t, resources.dictionary) for t in hotlist_titles
    ]
    hotlist_union: Set[str] = set()
    for es in hotlist_entity_sets:
        hotlist_union |= es
    if not hotlist_union:
        return []

    # admitted: (best_topic_index, overlap_count, title_item)
    admitted: List[tuple] = []
    for item in raw_rss_items:
        if not _within_window(item.get("published_at"), now, window_hours):
            continue
        ents = extract_entities(item.get("title", ""), resources.dictionary)
        if not ents:
            continue

        # Route 1 (corroboration, implemented): shares an entity with hotlist.
        # TODO(independent-english-stream issue): Route 2 — admit on English
        # keyword match here, and set drop_unmerged_rss=False downstream to keep
        # RSS-only candidates.  Out of scope for this change.
        if not (ents & hotlist_union):
            continue

        # Best-matching hotlist topic (max overlap) — only used for capping.
        best_topic = -1
        best_overlap = 0
        for ti, hset in enumerate(hotlist_entity_sets):
            ov = len(ents & hset)
            if ov > best_overlap:
                best_overlap, best_topic = ov, ti

        admitted.append((best_topic, best_overlap, _to_title_item(item)))

    if max_per_topic is not None and admitted:
        admitted = _cap_per_topic(admitted, max_per_topic)

    titles = [t for (_topic, _ov, t) in admitted]
    if not titles:
        return []
    return [{"word": None, "titles": titles}]


def _to_title_item(item: dict) -> dict:
    """Map a raw RSS dict to the title-item shape adapt_rss_stats consumes.

    Note ``feed_name`` -> ``source_name`` (the key _adapt_rss_title_item reads).
    """
    return {
        "title": item.get("title", ""),
        "feed_id": item.get("feed_id"),
        "source_name": item.get("feed_name", ""),
        "url": item.get("url"),
        "published_at": item.get("published_at"),
        "ranks": [],
        "count": 1,
        "is_new": None,
    }


def _cap_per_topic(admitted: List[tuple], max_per_topic: int) -> List[tuple]:
    """Keep at most max_per_topic RSS per best-matching hotlist topic."""
    by_topic: Dict[int, List[tuple]] = {}
    for entry in admitted:
        by_topic.setdefault(entry[0], []).append(entry)
    kept: List[tuple] = []
    for topic, entries in by_topic.items():
        entries.sort(key=lambda e: e[1], reverse=True)  # by overlap count, desc
        kept.extend(entries[:max_per_topic])
    return kept
