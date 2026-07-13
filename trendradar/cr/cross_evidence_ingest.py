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

from collections.abc import Mapping
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional, Set

from trendradar.cr.entity_match import EntityResources, extract_entities
from trendradar.cr.models import CRClusterConfig


_TRUTHY = frozenset({"1", "true", "yes", "on"})
_FALSY = frozenset({"0", "false", "no", "off"})


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
    # Match the existing RSS freshness convention: timezone-naive feed
    # timestamps are UTC.  Convert instants instead of relabelling them.
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    cutoff = now.astimezone(timezone.utc) - timedelta(hours=window_hours)
    return dt.astimezone(timezone.utc) >= cutoff


def _parse_bool_env(raw: str, key: str) -> bool:
    value = raw.strip().lower()
    if value in _TRUTHY:
        return True
    if value in _FALSY:
        return False
    raise ValueError(f"{key} must be a boolean-like value")


def build_cross_evidence_cluster_config_from_env(
    env: Mapping[str, str],
    *,
    base: CRClusterConfig | None = None,
) -> CRClusterConfig:
    """Resolve cross-evidence runtime knobs from an explicit environment."""
    config = base if base is not None else CRClusterConfig()

    enabled_key = "PTILOPSIS_CR_CROSS_EVIDENCE_RSS_ENABLED"
    enabled_raw = env.get(enabled_key)
    enabled = (
        _parse_bool_env(enabled_raw, enabled_key)
        if enabled_raw is not None
        else config.cross_evidence_rss_enabled
    )

    window_key = "PTILOPSIS_CR_CROSS_EVIDENCE_WINDOW_HOURS"
    window_raw = env.get(window_key)
    window_hours = config.cross_evidence_window_hours
    if window_raw is not None:
        try:
            window_hours = float(window_raw.strip())
        except (TypeError, ValueError):
            raise ValueError(f"{window_key} must be a positive number")
        if window_hours <= 0:
            raise ValueError(f"{window_key} must be a positive number")

    cap_key = "PTILOPSIS_CR_CROSS_EVIDENCE_MAX_PER_TOPIC"
    cap_raw = env.get(cap_key)
    max_per_topic = config.cross_evidence_max_per_topic
    if cap_raw is not None:
        normalized = cap_raw.strip().lower()
        if normalized in {"", "none", "off"}:
            max_per_topic = None
        else:
            try:
                max_per_topic = int(normalized)
            except (TypeError, ValueError):
                raise ValueError(f"{cap_key} must be a positive integer or none")
            if max_per_topic <= 0:
                raise ValueError(f"{cap_key} must be a positive integer or none")

    drop_key = "PTILOPSIS_CR_DROP_UNMERGED_RSS"
    drop_raw = env.get(drop_key)
    if drop_raw is not None:
        drop_unmerged_rss = _parse_bool_env(drop_raw, drop_key)
    elif base is not None:
        drop_unmerged_rss = config.drop_unmerged_rss
    else:
        # The production cross-evidence path is corroboration-only by default.
        # Disabling admission also restores the legacy RSS-only behavior.
        drop_unmerged_rss = enabled

    return replace(
        config,
        cross_evidence_rss_enabled=enabled,
        cross_evidence_window_hours=window_hours,
        cross_evidence_max_per_topic=max_per_topic,
        drop_unmerged_rss=drop_unmerged_rss,
    )


def merge_rss_stats(
    keyword_rss_stats: Optional[List[dict]],
    admitted_rss_stats: Optional[List[dict]],
) -> List[dict]:
    """Append unique admitted RSS items while preserving keyword groups."""
    merged = [
        {
            **group,
            "titles": [dict(item) for item in group.get("titles", [])],
        }
        for group in (keyword_rss_stats or [])
    ]
    seen = {
        _rss_item_identity(item): item
        for group in merged
        for item in group.get("titles", [])
    }
    admitted_unique: List[dict] = []
    for group in admitted_rss_stats or []:
        for item in group.get("titles", []):
            identity = _rss_item_identity(item)
            if identity in seen:
                existing = seen[identity]
                if (
                    existing.get("precomputed_entities") is None
                    and item.get("precomputed_entities") is not None
                ):
                    existing["precomputed_entities"] = list(
                        item["precomputed_entities"]
                    )
                continue
            copied = dict(item)
            seen[identity] = copied
            admitted_unique.append(copied)

    if admitted_unique:
        merged.append({"word": None, "titles": admitted_unique})
    return merged


def _rss_item_identity(item: dict) -> tuple:
    url = item.get("url")
    if url:
        return ("url", url)
    return (
        "item",
        item.get("feed_id"),
        item.get("title", ""),
        item.get("published_at"),
    )


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

        admitted.append(
            (best_topic, best_overlap, _to_title_item(item, ents))
        )

    if max_per_topic is not None and admitted:
        admitted = _cap_per_topic(admitted, max_per_topic)

    titles = [t for (_topic, _ov, t) in admitted]
    if not titles:
        return []
    return [{"word": None, "titles": titles}]


def _to_title_item(item: dict, entities: Set[str]) -> dict:
    """Map a raw RSS dict to the title-item shape adapt_rss_stats consumes.

    Note ``feed_name`` -> ``source_name`` (the key _adapt_rss_title_item reads).
    """
    return {
        "title": item.get("title", ""),
        "feed_id": item.get("feed_id"),
        "source_name": item.get("feed_name", ""),
        "url": item.get("url"),
        "published_at": item.get("published_at"),
        "summary": item.get("summary"),
        "author": item.get("author"),
        "cross_evidence_admitted": True,
        "precomputed_entities": sorted(entities),
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
