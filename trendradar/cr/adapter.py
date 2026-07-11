# coding=utf-8
"""
CR input adapter.

Converts existing hotlist / RSS stats into CR primitive records.
Does NOT score, decide, cluster, or render.

Design reference: docs/Ptilopsis_Radar_Push_System_Design.md v0.4.1 §7–§8.
"""

from __future__ import annotations

from typing import Dict, List, Optional

from trendradar.cr.models import (
    CRPrimitiveRecord,
    CRRunContext,
    CRSourceItem,
    _classify_rank,
    is_visible_rank,
)
from trendradar.cr.input_health import input_item_identity


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _is_reliable_timeline(
    rank_timeline: List[dict],
    mode: str,
) -> bool:
    """Determine whether a rank_timeline is reliable.

    Reliable means:
      - non-empty
      - from a current/daily mode (not incremental synthetic)
      - entries have actual rank data (not all None)

    Incremental items may lack rank_timeline or have synthetic title_info.
    We mark them unreliable rather than fabricating growth.
    """
    if not rank_timeline:
        return False
    # Incremental mode items do not have reliable timelines
    if mode == "incremental":
        return False
    # At least one entry must have a non-None rank
    return any(entry.get("rank") is not None for entry in rank_timeline)


def _count_visible_observations(rank_timeline: List[dict]) -> int:
    """Count observations in rank_timeline where rank is a visible positive int."""
    return sum(1 for entry in rank_timeline if is_visible_rank(entry.get("rank")))


def _latest_observation_rank(rank_timeline: List[dict]) -> Optional[int]:
    """Return the visible rank from the latest timeline entry, or None.

    This is the true current observation rank — distinct from
    ``normalized_rank`` which is the best (min) rank across all observations.
    """
    if not rank_timeline:
        return None
    latest_rank = rank_timeline[-1].get("rank")
    return latest_rank if is_visible_rank(latest_rank) else None


def _derive_previous_observation(
    rank_timeline: List[dict],
    current_rank: Optional[int],
    current_visible: bool,
) -> dict:
    """Derive previous observation fields from a reliable rank_timeline.

    Args:
        rank_timeline: The full rank timeline (must be reliable).
        current_rank: The latest observation rank (from ``_latest_observation_rank``),
            NOT the best-rank representative (``normalized_rank``).
        current_visible: Whether ``current_rank`` is a visible rank.

    Returns dict with keys:
      previous_observation_exists, previous_observation_visible,
      previous_visible_rank, current_rank, rank_delta

    Contract (design §8.5, refined):

    previous_observation_exists:
      True when at least one observation precedes the current one in timeline.

    previous_observation_visible:
      True only when the **immediate** previous observation is visible.
      For 50 → None → 10 the immediate previous is None → False (re-entry).
      For 30 → 10 the immediate previous is 30 → True (rank improvement).

    previous_visible_rank:
      The most recent visible rank before current (may come from a non-
      immediate ancestor).  Useful for debug/context but NOT for rank_delta.

    rank_delta:
      Only computed when previous_observation_visible is True and current is
      visible.  Uses ``current_rank`` (latest observation), not
      ``normalized_rank`` (best representative).
      rank_delta = previous_visible_rank - current_rank (positive = improved).

    ranks (distinct list) must NOT be used.
    """
    result = {
        "previous_observation_exists": False,
        "previous_observation_visible": False,
        "previous_visible_rank": None,
        "current_rank": current_rank if current_visible else None,
        "rank_delta": None,
    }

    if len(rank_timeline) < 2:
        return result

    # There is at least one observation before the current one.
    result["previous_observation_exists"] = True

    # --- immediate previous entry ---
    immediate_prev = rank_timeline[-2]
    immediate_prev_rank = immediate_prev.get("rank")
    immediate_prev_visible = is_visible_rank(immediate_prev_rank)

    # --- most recent visible rank before current ---
    most_recent_visible_rank: Optional[int] = None
    # Walk from second-newest to oldest
    for entry in reversed(rank_timeline[:-1]):
        rank = entry.get("rank")
        if is_visible_rank(rank):
            most_recent_visible_rank = rank
            break

    result["previous_visible_rank"] = most_recent_visible_rank

    if immediate_prev_visible:
        result["previous_observation_visible"] = True
        if current_visible and current_rank is not None and most_recent_visible_rank is not None:
            result["rank_delta"] = most_recent_visible_rank - current_rank
    else:
        result["previous_observation_visible"] = False

    return result


def _derive_time_signals(
    first_time: Optional[str],
    last_time: Optional[str],
    mode: str,
) -> dict:
    """Derive time signal flags.

    Design §8.6:
      incremental synthetic title_info may set first_time == last_time == now → mark synthetic.
      run_time_inferred is informational, not a penalty.
    """
    has_time = bool(first_time or last_time)
    synthetic = False
    if mode == "incremental" and has_time:
        if first_time and first_time == last_time:
            synthetic = True

    return {
        "has_time_signals": has_time,
        "time_signals_synthetic": synthetic,
        "run_time_inferred": False,
    }


def _derive_count_semantics(
    count: Optional[int],
    source_type: str,
) -> dict:
    """Derive count fields and semantics.

    Design §8.8:
      hotlist → crawl_count
      rss → rss_item_count (or group_count if grouped)
    """
    has = count is not None and count > 0
    if source_type == "hotlist":
        semantics = "crawl_count" if has else "unknown"
    elif source_type == "rss":
        semantics = "rss_item_count" if has else "unknown"
    else:
        semantics = "unknown"

    return {
        "has_count": has,
        "count_semantics": semantics,
    }


def _derive_is_new_semantics(
    is_new: Optional[bool],
    first_crawl_of_day: Optional[bool],
    mode: str,
) -> str:
    """Derive is_new_semantics.

    Design §8.7:
      first_crawl_of_day == true → is_new may be inflated → "incremental_first_crawl"
      is_new true but not first crawl → "new_titles_detection"
      is_new false / None → "unknown" (semantics don't matter for non-new items)

    The ``mode`` parameter is accepted for future extension but currently does
    not change the return value; both incremental and non-incremental paths
    produce "new_titles_detection" when is_new is true and first crawl is not
    active.
    """
    if not is_new:
        return "unknown"

    # is_new is True
    if first_crawl_of_day is True:
        return "incremental_first_crawl"
    return "new_titles_detection"


# ---------------------------------------------------------------------------
# Hotlist adapter
# ---------------------------------------------------------------------------


def _adapt_hotlist_title_item(
    title_item: dict,
    keyword_group: Optional[str],
    context: CRRunContext,
) -> CRSourceItem:
    """Convert one hotlist stats title item into a CRSourceItem."""
    # Rank normalization
    raw_ranks = title_item.get("ranks", [])
    # Use min rank as the representative "current" rank (best position)
    # If no ranks, treat as missing
    raw_rank: Optional[int] = None
    if raw_ranks:
        # Use the minimum (best) rank as representative
        valid_ranks = [r for r in raw_ranks if is_visible_rank(r)]
        if valid_ranks:
            raw_rank = min(valid_ranks)
        else:
            # All ranks are sentinel — pick the first non-None for raw display
            for r in raw_ranks:
                if r is not None:
                    raw_rank = r
                    break

    normalized_rank, is_visible, rank_sentinel = _classify_rank(raw_rank)

    # Rank timeline
    rank_timeline = title_item.get("rank_timeline", [])
    mode = context.mode or "unknown"
    reliable = _is_reliable_timeline(rank_timeline, mode)
    vis_count = _count_visible_observations(rank_timeline) if reliable else 0

    # current_rank: latest observation rank when reliable, else fallback to
    # normalized_rank (best representative).
    # normalized_rank stays as min(valid_ranks) — best known visible rank.
    if reliable:
        current_rank = _latest_observation_rank(rank_timeline)
    else:
        current_rank = normalized_rank if is_visible else None
    current_visible = current_rank is not None

    # Previous observation (only from reliable timeline).
    # Uses current_rank (latest observation), not normalized_rank (best).
    prev_obs = {}
    if reliable:
        prev_obs = _derive_previous_observation(rank_timeline, current_rank, current_visible)

    # Time signals
    first_time = title_item.get("first_time") or None
    last_time = title_item.get("last_time") or None
    time_sig = _derive_time_signals(first_time, last_time, mode)

    # is_new semantics
    is_new = title_item.get("is_new")
    is_new_sem = _derive_is_new_semantics(
        is_new, context.first_crawl_of_day, mode,
    )

    # Count
    count = title_item.get("count")
    count_sig = _derive_count_semantics(count, "hotlist")

    observed_identity = input_item_identity(
        source_type="hotlist",
        source_id=title_item.get("source_id"),
        title=title_item.get("title", ""),
    )
    return CRSourceItem(
        source_type="hotlist",
        source_id=title_item.get("source_id"),
        feed_id=None,
        source_name=title_item.get("source_name", ""),
        title=title_item.get("title", ""),
        url=title_item.get("url") or title_item.get("mobileUrl") or None,
        keyword_group=keyword_group,
        keyword_groups=[keyword_group] if keyword_group else None,
        is_new=is_new if isinstance(is_new, bool) else None,
        is_new_semantics=is_new_sem,
        raw_rank=raw_rank,
        normalized_rank=normalized_rank,
        is_visible=is_visible,
        rank_sentinel=rank_sentinel,
        rank_timeline=rank_timeline,
        has_rank_timeline=bool(rank_timeline),
        has_reliable_rank_timeline=reliable,
        visible_observation_count=vis_count,
        previous_observation_exists=prev_obs.get("previous_observation_exists", False),
        previous_observation_visible=prev_obs.get("previous_observation_visible", False),
        previous_visible_rank=prev_obs.get("previous_visible_rank"),
        current_rank=current_rank,
        rank_delta=prev_obs.get("rank_delta"),
        first_time=first_time,
        last_time=last_time,
        has_time_signals=time_sig["has_time_signals"],
        time_signals_synthetic=time_sig["time_signals_synthetic"],
        run_time_inferred=time_sig["run_time_inferred"],
        first_crawl_of_day=context.first_crawl_of_day,
        count=count,
        has_count=count_sig["has_count"],
        count_semantics=count_sig["count_semantics"],
        observed_in_current_run=(
            observed_identity in context.observed_item_identities
        ),
    )


def adapt_hotlist_stats(
    stats: List[Dict],
    *,
    context: CRRunContext,
) -> List[CRPrimitiveRecord]:
    """Adapt hotlist stats (from count_word_frequency) into CR primitive records.

    Args:
        stats: Output of count_word_frequency(), a list of keyword-group dicts.
               Each dict has keys: word, count, position, titles, percentage.
        context: Run-level context (mode, first_crawl_of_day, etc.).

    Returns:
        List of CRPrimitiveRecord, one per keyword group with items.
    """
    records: List[CRPrimitiveRecord] = []

    for group in stats:
        group_name = group.get("word")
        titles = group.get("titles", [])
        if not titles:
            continue

        items = [
            _adapt_hotlist_title_item(t, group_name, context)
            for t in titles
        ]

        # Primary title: the first item's title (conservative; PR9c does heat-based selection)
        primary_title = items[0].title if items else None
        representative_url = items[0].url if items else None

        records.append(CRPrimitiveRecord(
            keyword_group=group_name,
            keyword_groups=[group_name] if group_name else [],
            source_items=items,
            primary_title=primary_title,
            representative_url=representative_url,
            record_source="hotlist_stats",
        ))

    return records


# ---------------------------------------------------------------------------
# RSS adapter
# ---------------------------------------------------------------------------


def _adapt_rss_title_item(
    title_item: dict,
    keyword_group: Optional[str],
    context: CRRunContext,
) -> CRSourceItem:
    """Convert one RSS stats title item into a CRSourceItem.

    RSS ranks are pseudo-ranks (published order).  They must NOT be used
    for rank-based heat / growth scoring.
    """
    mode = context.mode or "unknown"

    # RSS has no reliable rank_timeline
    rank_timeline: List[dict] = []
    reliable = False

    # is_new semantics
    is_new = title_item.get("is_new")
    is_new_sem = _derive_is_new_semantics(
        is_new, context.first_crawl_of_day, mode,
    )

    # Time signals — RSS may have published_at as the time signal
    first_time = title_item.get("first_time") or title_item.get("published_at") or None
    last_time = title_item.get("last_time") or None
    # For RSS, if first_time comes from published_at, it's not "synthetic" in the
    # incremental sense, but it's also not a crawl-observation time.
    time_sig = _derive_time_signals(first_time, last_time, mode)

    # Count
    count = title_item.get("count")
    count_sig = _derive_count_semantics(count, "rss")

    # RSS pseudo-rank — explicitly mark as not for scoring
    raw_ranks = title_item.get("ranks", [])
    raw_rank: Optional[int] = raw_ranks[0] if raw_ranks else None

    # RSS ranks are NOT hotlist ranks.  We do NOT normalize them as visible.
    # The design says: RSS published-order pseudo-rank must never enter
    # Rank Movement or Current Heat rank scoring (§8.2).
    normalized_rank = None
    is_visible = False
    rank_sentinel = "missing"

    observed_identity = input_item_identity(
        source_type="rss",
        feed_id=title_item.get("feed_id") or None,
        title=title_item.get("title", ""),
        url=title_item.get("url") or None,
    )
    return CRSourceItem(
        source_type="rss",
        source_id=None,
        feed_id=title_item.get("feed_id") or None,
        source_name=title_item.get("source_name", ""),
        title=title_item.get("title", ""),
        url=title_item.get("url") or None,
        keyword_group=keyword_group,
        keyword_groups=[keyword_group] if keyword_group else None,
        is_new=is_new if isinstance(is_new, bool) else None,
        is_new_semantics=is_new_sem,
        raw_rank=raw_rank,
        normalized_rank=normalized_rank,
        is_visible=is_visible,
        rank_sentinel=rank_sentinel,
        rank_timeline=rank_timeline,
        has_rank_timeline=False,
        has_reliable_rank_timeline=False,
        visible_observation_count=0,
        previous_observation_exists=False,
        previous_observation_visible=False,
        previous_visible_rank=None,
        current_rank=None,
        rank_delta=None,
        first_time=first_time,
        last_time=last_time,
        has_time_signals=time_sig["has_time_signals"],
        time_signals_synthetic=time_sig["time_signals_synthetic"],
        run_time_inferred=time_sig["run_time_inferred"],
        first_crawl_of_day=context.first_crawl_of_day,
        count=count,
        has_count=count_sig["has_count"],
        count_semantics=count_sig["count_semantics"],
        published_at=title_item.get("published_at") or None,
        summary=title_item.get("summary") or None,
        author=title_item.get("author") or None,
        cross_evidence_admitted=bool(title_item.get("cross_evidence_admitted")),
        observed_in_current_run=(
            observed_identity in context.observed_item_identities
        ),
    )


def adapt_rss_stats(
    rss_stats: List[Dict],
    *,
    context: CRRunContext,
) -> List[CRPrimitiveRecord]:
    """Adapt RSS stats (from count_rss_frequency) into CR primitive records.

    Args:
        rss_stats: Output of count_rss_frequency(), a list of keyword-group dicts.
        context: Run-level context.

    Returns:
        List of CRPrimitiveRecord, one per keyword group with items.
    """
    records: List[CRPrimitiveRecord] = []

    for group in rss_stats:
        group_name = group.get("word")
        titles = group.get("titles", [])
        if not titles:
            continue

        items = [
            _adapt_rss_title_item(t, group_name, context)
            for t in titles
        ]

        primary_title = items[0].title if items else None
        representative_url = items[0].url if items else None

        records.append(CRPrimitiveRecord(
            keyword_group=group_name,
            keyword_groups=[group_name] if group_name else [],
            source_items=items,
            primary_title=primary_title,
            representative_url=representative_url,
            record_source="rss_stats",
        ))

    return records
