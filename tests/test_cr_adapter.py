# coding=utf-8
"""
PR9b: CR primitive model + input adapter tests.

Covers:
  - hotlist title item → CRSourceItem
  - RSS title item → CRSourceItem
  - rank sentinel normalization (0, 99, None, missing)
  - rank_timeline reliability
  - previous observation extraction from rank_timeline
  - first_crawl_of_day / is_new_semantics
  - synthetic time signals
  - count semantics
  - primitive record creation
  - no scoring / decision fields produced
"""

import os
import sys
import unittest

# Ensure project root is on path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from trendradar.cr.models import (
    CRPrimitiveRecord,
    CRRunContext,
    CRSourceItem,
    RANK_SENTINELS,
    _classify_rank,
    is_visible_rank,
)
from trendradar.cr.adapter import (
    adapt_hotlist_stats,
    adapt_rss_stats,
    _derive_previous_observation,
    _is_reliable_timeline,
    _count_visible_observations,
    _latest_observation_rank,
)
from trendradar.cr.input_health import (
    evaluate_cr_input_health,
    input_item_identity,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_hotlist_item(
    title="Test Title",
    source_name="weibo",
    source_id="weibo",
    ranks=None,
    rank_timeline=None,
    first_time="09:30",
    last_time="12:00",
    count=3,
    is_new=False,
    url="https://example.com",
):
    """Build a hotlist stats title item (mimics count_word_frequency output)."""
    if ranks is None:
        ranks = [5]
    item = {
        "title": title,
        "source_name": source_name,
        "source_id": source_id,
        "ranks": ranks,
        "count": count,
        "first_time": first_time,
        "last_time": last_time,
        "url": url,
        "mobileUrl": "",
        "is_new": is_new,
        "rank_timeline": rank_timeline or [],
    }
    return item


def _make_rss_item(
    title="RSS Title",
    source_name="Hacker News",
    feed_id="hacker-news",
    ranks=None,
    first_time="2026-06-08T08:00:00+08:00",
    last_time="",
    count=1,
    is_new=False,
    url="https://hn.example.com/1",
    published_at="2026-06-08T08:00:00+08:00",
    summary="A summary",
    author="Author Name",
):
    """Build an RSS stats title item (mimics count_rss_frequency output)."""
    if ranks is None:
        ranks = [1]
    return {
        "title": title,
        "source_name": source_name,
        "feed_id": feed_id,
        "ranks": ranks,
        "count": count,
        "first_time": first_time,
        "last_time": last_time,
        "url": url,
        "mobile_url": "",
        "is_new": is_new,
        "published_at": published_at,
        "summary": summary,
        "author": author,
    }


def _ctx(mode="current", first_crawl=False):
    return CRRunContext(mode=mode, first_crawl_of_day=first_crawl)


# ---------------------------------------------------------------------------
# Rank sentinel normalization
# ---------------------------------------------------------------------------


class TestRankSentinelNormalization(unittest.TestCase):
    """Design §8.3: rank in {0, 99, None, missing} → not visible."""

    def test_rank_zero_not_visible(self):
        rank, vis, sentinel = _classify_rank(0)
        self.assertIsNone(rank)
        self.assertFalse(vis)
        self.assertEqual(sentinel, "zero")

    def test_rank_ninety_nine_not_visible(self):
        rank, vis, sentinel = _classify_rank(99)
        self.assertIsNone(rank)
        self.assertFalse(vis)
        self.assertEqual(sentinel, "ninety_nine")

    def test_rank_none_not_visible(self):
        rank, vis, sentinel = _classify_rank(None)
        self.assertIsNone(rank)
        self.assertFalse(vis)
        self.assertEqual(sentinel, "missing")

    def test_rank_negative_not_visible(self):
        rank, vis, sentinel = _classify_rank(-1)
        self.assertIsNone(rank)
        self.assertFalse(vis)
        self.assertEqual(sentinel, "missing")

    def test_valid_rank_visible(self):
        for r in [1, 10, 50, 100]:
            rank, vis, sentinel = _classify_rank(r)
            self.assertEqual(rank, r)
            self.assertTrue(vis)
            self.assertEqual(sentinel, "none")


# ---------------------------------------------------------------------------
# is_visible_rank — single source of truth
# ---------------------------------------------------------------------------


class TestIsVisibleRank(unittest.TestCase):
    """is_visible_rank() is the canonical visibility check used everywhere."""

    def test_none_not_visible(self):
        self.assertFalse(is_visible_rank(None))

    def test_zero_not_visible(self):
        self.assertFalse(is_visible_rank(0))

    def test_ninety_nine_not_visible(self):
        self.assertFalse(is_visible_rank(99))

    def test_negative_not_visible(self):
        self.assertFalse(is_visible_rank(-1))

    def test_rank_1_visible(self):
        self.assertTrue(is_visible_rank(1))

    def test_rank_10_visible(self):
        self.assertTrue(is_visible_rank(10))

    def test_rank_50_visible(self):
        self.assertTrue(is_visible_rank(50))

    def test_rank_100_visible(self):
        self.assertTrue(is_visible_rank(100))

    def test_classify_uses_same_visibility(self):
        """_classify_rank visibility matches is_visible_rank."""
        for r in [None, 0, 1, 10, 50, 99, 100, -1]:
            _, classify_vis, _ = _classify_rank(r)
            self.assertEqual(
                classify_vis, is_visible_rank(r),
                f"disagree on rank={r}",
            )

    def test_ranks_sentinels_constant(self):
        """RANK_SENTINELS is the single definition used by is_visible_rank."""
        self.assertEqual(RANK_SENTINELS, {0, 99})
        for s in RANK_SENTINELS:
            self.assertFalse(is_visible_rank(s))


# ---------------------------------------------------------------------------
# Hotlist adapter: source_type and basic fields
# ---------------------------------------------------------------------------


class TestHotlistSourceItem(unittest.TestCase):
    """Hotlist title item → CRSourceItem with source_type=hotlist."""

    def test_source_type_hotlist(self):
        stats = [{"word": "group1", "titles": [_make_hotlist_item()], "count": 1, "position": 0}]
        records = adapt_hotlist_stats(stats, context=_ctx())
        self.assertEqual(len(records), 1)
        item = records[0].source_items[0]
        self.assertEqual(item.source_type, "hotlist")

    def test_source_id_preserved(self):
        stats = [{"word": "g", "titles": [_make_hotlist_item(source_id="toutiao")], "count": 1, "position": 0}]
        records = adapt_hotlist_stats(stats, context=_ctx())
        item = records[0].source_items[0]
        self.assertEqual(item.source_id, "toutiao")

    def test_normalized_rank_visible(self):
        stats = [{"word": "g", "titles": [_make_hotlist_item(ranks=[10])], "count": 1, "position": 0}]
        records = adapt_hotlist_stats(stats, context=_ctx())
        item = records[0].source_items[0]
        self.assertTrue(item.is_visible)
        self.assertEqual(item.normalized_rank, 10)
        self.assertEqual(item.rank_sentinel, "none")

    def test_normalized_rank_uses_best_rank(self):
        """normalized_rank uses min(valid_ranks) as representative."""
        stats = [{"word": "g", "titles": [_make_hotlist_item(ranks=[30, 10, 20])], "count": 1, "position": 0}]
        records = adapt_hotlist_stats(stats, context=_ctx())
        item = records[0].source_items[0]
        self.assertEqual(item.normalized_rank, 10)
        self.assertTrue(item.is_visible)

    def test_all_sentinel_ranks_not_visible(self):
        stats = [{"word": "g", "titles": [_make_hotlist_item(ranks=[0, 99])], "count": 1, "position": 0}]
        records = adapt_hotlist_stats(stats, context=_ctx())
        item = records[0].source_items[0]
        self.assertFalse(item.is_visible)
        self.assertIsNone(item.normalized_rank)

    def test_empty_ranks_not_visible(self):
        stats = [{"word": "g", "titles": [_make_hotlist_item(ranks=[])], "count": 1, "position": 0}]
        records = adapt_hotlist_stats(stats, context=_ctx())
        item = records[0].source_items[0]
        self.assertFalse(item.is_visible)
        self.assertIsNone(item.raw_rank)


# ---------------------------------------------------------------------------
# Hotlist adapter: rank sentinel via adapter
# ---------------------------------------------------------------------------


class TestHotlistRankSentinelViaAdapter(unittest.TestCase):
    """Full adapter path for rank sentinels: 0, 99, None, missing."""

    def test_rank_0_not_visible(self):
        stats = [{"word": "g", "titles": [_make_hotlist_item(ranks=[0])], "count": 1, "position": 0}]
        item = adapt_hotlist_stats(stats, context=_ctx())[0].source_items[0]
        self.assertFalse(item.is_visible)
        self.assertIsNone(item.normalized_rank)
        self.assertEqual(item.rank_sentinel, "zero")

    def test_rank_99_not_visible(self):
        stats = [{"word": "g", "titles": [_make_hotlist_item(ranks=[99])], "count": 1, "position": 0}]
        item = adapt_hotlist_stats(stats, context=_ctx())[0].source_items[0]
        self.assertFalse(item.is_visible)
        self.assertIsNone(item.normalized_rank)
        self.assertEqual(item.rank_sentinel, "ninety_nine")

    def test_rank_1_visible(self):
        stats = [{"word": "g", "titles": [_make_hotlist_item(ranks=[1])], "count": 1, "position": 0}]
        item = adapt_hotlist_stats(stats, context=_ctx())[0].source_items[0]
        self.assertTrue(item.is_visible)
        self.assertEqual(item.normalized_rank, 1)

    def test_rank_10_visible(self):
        stats = [{"word": "g", "titles": [_make_hotlist_item(ranks=[10])], "count": 1, "position": 0}]
        item = adapt_hotlist_stats(stats, context=_ctx())[0].source_items[0]
        self.assertTrue(item.is_visible)
        self.assertEqual(item.normalized_rank, 10)

    def test_rank_50_visible(self):
        stats = [{"word": "g", "titles": [_make_hotlist_item(ranks=[50])], "count": 1, "position": 0}]
        item = adapt_hotlist_stats(stats, context=_ctx())[0].source_items[0]
        self.assertTrue(item.is_visible)
        self.assertEqual(item.normalized_rank, 50)


# ---------------------------------------------------------------------------
# RSS adapter: source_type, metadata, rank protection
# ---------------------------------------------------------------------------


class TestRSSSourceItem(unittest.TestCase):
    """RSS title item → CRSourceItem with source_type=rss."""

    def test_source_type_rss(self):
        stats = [{"word": "g", "titles": [_make_rss_item()], "count": 1, "position": 0}]
        records = adapt_rss_stats(stats, context=_ctx())
        item = records[0].source_items[0]
        self.assertEqual(item.source_type, "rss")

    def test_feed_id_preserved(self):
        stats = [{"word": "g", "titles": [_make_rss_item(feed_id="hacker-news")], "count": 1, "position": 0}]
        item = adapt_rss_stats(stats, context=_ctx())[0].source_items[0]
        self.assertEqual(item.feed_id, "hacker-news")

    def test_published_at_preserved(self):
        pub = "2026-06-08T08:00:00+08:00"
        stats = [{"word": "g", "titles": [_make_rss_item(published_at=pub)], "count": 1, "position": 0}]
        item = adapt_rss_stats(stats, context=_ctx())[0].source_items[0]
        self.assertEqual(item.published_at, pub)

    def test_summary_preserved(self):
        stats = [{"word": "g", "titles": [_make_rss_item(summary="test summary")], "count": 1, "position": 0}]
        item = adapt_rss_stats(stats, context=_ctx())[0].source_items[0]
        self.assertEqual(item.summary, "test summary")

    def test_author_preserved(self):
        stats = [{"word": "g", "titles": [_make_rss_item(author="John")], "count": 1, "position": 0}]
        item = adapt_rss_stats(stats, context=_ctx())[0].source_items[0]
        self.assertEqual(item.author, "John")

    def test_rss_rank_not_visible(self):
        """RSS pseudo-rank must NOT create hotlist visibility."""
        stats = [{"word": "g", "titles": [_make_rss_item(ranks=[1])], "count": 1, "position": 0}]
        item = adapt_rss_stats(stats, context=_ctx())[0].source_items[0]
        self.assertFalse(item.is_visible)
        self.assertIsNone(item.normalized_rank)
        self.assertEqual(item.rank_sentinel, "missing")

    def test_rss_no_rank_timeline(self):
        stats = [{"word": "g", "titles": [_make_rss_item()], "count": 1, "position": 0}]
        item = adapt_rss_stats(stats, context=_ctx())[0].source_items[0]
        self.assertFalse(item.has_rank_timeline)
        self.assertFalse(item.has_reliable_rank_timeline)
        self.assertEqual(item.visible_observation_count, 0)


# ---------------------------------------------------------------------------
# Rank timeline reliability
# ---------------------------------------------------------------------------


class TestRankTimelineReliability(unittest.TestCase):
    """Design §8.4: reliable vs unreliable rank_timeline."""

    def test_reliable_timeline_current_mode(self):
        timeline = [
            {"time": "09:30", "rank": 30},
            {"time": "10:00", "rank": 10},
        ]
        stats = [{"word": "g", "titles": [_make_hotlist_item(rank_timeline=timeline)], "count": 1, "position": 0}]
        item = adapt_hotlist_stats(stats, context=_ctx(mode="current"))[0].source_items[0]
        self.assertTrue(item.has_rank_timeline)
        self.assertTrue(item.has_reliable_rank_timeline)
        self.assertEqual(item.visible_observation_count, 2)

    def test_missing_timeline_not_reliable(self):
        stats = [{"word": "g", "titles": [_make_hotlist_item(rank_timeline=[])], "count": 1, "position": 0}]
        item = adapt_hotlist_stats(stats, context=_ctx(mode="current"))[0].source_items[0]
        self.assertFalse(item.has_rank_timeline)
        self.assertFalse(item.has_reliable_rank_timeline)
        self.assertEqual(item.visible_observation_count, 0)

    def test_incremental_timeline_not_reliable(self):
        """Incremental synthetic title_info should not have reliable timeline."""
        timeline = [{"time": "09:30", "rank": 10}]
        stats = [{"word": "g", "titles": [_make_hotlist_item(rank_timeline=timeline)], "count": 1, "position": 0}]
        item = adapt_hotlist_stats(stats, context=_ctx(mode="incremental"))[0].source_items[0]
        self.assertTrue(item.has_rank_timeline)  # has data
        self.assertFalse(item.has_reliable_rank_timeline)  # but not reliable
        self.assertEqual(item.visible_observation_count, 0)

    def test_visible_observation_count_excludes_sentinels(self):
        timeline = [
            {"time": "09:30", "rank": 10},
            {"time": "09:45", "rank": None},  # 脱榜
            {"time": "10:00", "rank": 5},
            {"time": "10:15", "rank": 0},  # sentinel
            {"time": "10:30", "rank": 99},  # sentinel
        ]
        stats = [{"word": "g", "titles": [_make_hotlist_item(rank_timeline=timeline)], "count": 1, "position": 0}]
        item = adapt_hotlist_stats(stats, context=_ctx(mode="current"))[0].source_items[0]
        self.assertEqual(item.visible_observation_count, 2)  # rank 10 and rank 5


class TestIsReliableTimeline(unittest.TestCase):
    """Direct tests for _is_reliable_timeline helper."""

    def test_empty_not_reliable(self):
        self.assertFalse(_is_reliable_timeline([], "current"))

    def test_incremental_not_reliable(self):
        timeline = [{"time": "09:30", "rank": 10}]
        self.assertFalse(_is_reliable_timeline(timeline, "incremental"))

    def test_current_with_data_reliable(self):
        timeline = [{"time": "09:30", "rank": 10}]
        self.assertTrue(_is_reliable_timeline(timeline, "current"))

    def test_daily_with_data_reliable(self):
        timeline = [{"time": "09:30", "rank": 10}]
        self.assertTrue(_is_reliable_timeline(timeline, "daily"))

    def test_all_none_ranks_not_reliable(self):
        timeline = [
            {"time": "09:30", "rank": None},
            {"time": "10:00", "rank": None},
        ]
        self.assertFalse(_is_reliable_timeline(timeline, "current"))


# ---------------------------------------------------------------------------
# Previous observation extraction
# ---------------------------------------------------------------------------


class TestPreviousObservation(unittest.TestCase):
    """Design §8.5: previous rank from rank_timeline, NOT from ranks[-2].

    Note: ``_derive_previous_observation`` expects ``current_rank`` from
    ``_latest_observation_rank`` (latest timeline entry), NOT from
    ``normalized_rank`` (best representative rank).
    """

    def test_timeline_30_to_10_delta_20(self):
        """timeline: 30 → 10, rank_delta = 20."""
        timeline = [
            {"time": "09:30", "rank": 30},
            {"time": "10:00", "rank": 10},
        ]
        # current_rank = latest observation = 10
        result = _derive_previous_observation(timeline, 10, True)
        self.assertTrue(result["previous_observation_exists"])
        self.assertTrue(result["previous_observation_visible"])
        self.assertEqual(result["previous_visible_rank"], 30)
        self.assertEqual(result["rank_delta"], 20)

    def test_timeline_none_to_10_previous_not_visible(self):
        """timeline: None → 10, previous exists but not visible."""
        timeline = [
            {"time": "09:30", "rank": None},
            {"time": "10:00", "rank": 10},
        ]
        result = _derive_previous_observation(timeline, 10, True)
        self.assertTrue(result["previous_observation_exists"])
        self.assertFalse(result["previous_observation_visible"])
        self.assertIsNone(result["previous_visible_rank"])
        self.assertIsNone(result["rank_delta"])

    def test_timeline_one_point_no_previous(self):
        """Only one observation → previous_observation_exists = False."""
        timeline = [{"time": "10:00", "rank": 10}]
        result = _derive_previous_observation(timeline, 10, True)
        self.assertFalse(result["previous_observation_exists"])
        self.assertFalse(result["previous_observation_visible"])
        self.assertIsNone(result["previous_visible_rank"])
        self.assertIsNone(result["rank_delta"])

    def test_ranks_distinct_list_not_used(self):
        """ranks (distinct list) must NOT be used as previous observation source."""
        timeline = [{"time": "10:00", "rank": 10}]
        result = _derive_previous_observation(timeline, 10, True)
        # Should NOT see previous_visible_rank=30 from ranks
        self.assertFalse(result["previous_observation_exists"])

    def test_empty_timeline(self):
        result = _derive_previous_observation([], 10, True)
        self.assertFalse(result["previous_observation_exists"])

    def test_timeline_50_30_10_immediate_visible(self):
        """50 → 30 → 10.  Immediate previous is 30 (visible) → rank improvement."""
        timeline = [
            {"time": "09:00", "rank": 50},
            {"time": "09:30", "rank": 30},
            {"time": "10:00", "rank": 10},
        ]
        # current_rank = latest observation = 10
        result = _derive_previous_observation(timeline, 10, True)
        self.assertTrue(result["previous_observation_exists"])
        self.assertTrue(result["previous_observation_visible"])
        self.assertEqual(result["previous_visible_rank"], 30)
        self.assertEqual(result["rank_delta"], 20)

    def test_timeline_with_off_list_then_reentry(self):
        """50 → None → 10.  This is a re-entry, not rank improvement.

        immediate previous = None (not visible) → previous_observation_visible = False
        previous_visible_rank = 50 (most recent visible before current, for debug)
        rank_delta = None (do not treat re-entry as continuous improvement)
        """
        timeline = [
            {"time": "09:00", "rank": 50},
            {"time": "09:30", "rank": None},
            {"time": "10:00", "rank": 10},
        ]
        # current_rank = latest observation = 10
        result = _derive_previous_observation(timeline, 10, True)
        self.assertTrue(result["previous_observation_exists"])
        self.assertFalse(result["previous_observation_visible"])
        self.assertEqual(result["previous_visible_rank"], 50)
        self.assertIsNone(result["rank_delta"])


class TestPreviousObservationViaAdapter(unittest.TestCase):
    """Previous observation fields through the full adapter path."""

    def test_reliable_timeline_previous_exists(self):
        timeline = [
            {"time": "09:30", "rank": 30},
            {"time": "10:00", "rank": 10},
        ]
        stats = [{"word": "g", "titles": [_make_hotlist_item(rank_timeline=timeline, ranks=[10])], "count": 1, "position": 0}]
        item = adapt_hotlist_stats(stats, context=_ctx(mode="current"))[0].source_items[0]
        self.assertTrue(item.previous_observation_exists)
        self.assertTrue(item.previous_observation_visible)
        self.assertEqual(item.previous_visible_rank, 30)
        self.assertEqual(item.current_rank, 10)
        self.assertEqual(item.rank_delta, 20)

    def test_no_reliable_timeline_previous_unavailable(self):
        """Without reliable timeline, previous fields are unavailable."""
        stats = [{"word": "g", "titles": [_make_hotlist_item(rank_timeline=[])], "count": 1, "position": 0}]
        item = adapt_hotlist_stats(stats, context=_ctx(mode="current"))[0].source_items[0]
        self.assertFalse(item.previous_observation_exists)
        self.assertIsNone(item.previous_visible_rank)
        self.assertIsNone(item.rank_delta)

    def test_incremental_no_reliable_timeline(self):
        """Incremental mode → timeline unreliable → previous unavailable."""
        timeline = [{"time": "09:30", "rank": 30}, {"time": "10:00", "rank": 10}]
        stats = [{"word": "g", "titles": [_make_hotlist_item(rank_timeline=timeline, ranks=[10])], "count": 1, "position": 0}]
        item = adapt_hotlist_stats(stats, context=_ctx(mode="incremental"))[0].source_items[0]
        self.assertFalse(item.has_reliable_rank_timeline)
        self.assertFalse(item.previous_observation_exists)
        self.assertIsNone(item.rank_delta)


# ---------------------------------------------------------------------------
# current_rank vs normalized_rank semantics
# ---------------------------------------------------------------------------


class TestCurrentRankSemantics(unittest.TestCase):
    """current_rank is the latest observation rank, not best representative.

    normalized_rank = min(valid_ranks) — best known visible rank (representative).
    current_rank = latest timeline observation rank (when reliable).
    rank_delta uses current_rank, not normalized_rank.
    """

    def test_latest_differs_from_best_rank(self):
        """Case 1: latest observation (15) differs from best rank (5).

        timeline: 30 → 15
        ranks: [5, 15, 30]
        normalized_rank = 5 (best representative)
        current_rank = 15 (latest observation)
        previous_visible_rank = 30
        rank_delta = 15
        """
        timeline = [
            {"time": "09:00", "rank": 30},
            {"time": "09:30", "rank": 15},
        ]
        stats = [{"word": "g", "titles": [_make_hotlist_item(
            rank_timeline=timeline, ranks=[5, 15, 30],
        )], "count": 1, "position": 0}]
        item = adapt_hotlist_stats(stats, context=_ctx(mode="current"))[0].source_items[0]
        self.assertEqual(item.normalized_rank, 5)
        self.assertEqual(item.current_rank, 15)
        self.assertEqual(item.previous_visible_rank, 30)
        self.assertEqual(item.rank_delta, 15)

    def test_latest_not_visible_current_rank_none(self):
        """Case 2: latest observation is not visible → current_rank = None.

        timeline: 30 → None
        ranks: [30]
        normalized_rank = 30 (best representative)
        current_rank = None (latest not visible)
        previous_observation_exists = True
        previous_observation_visible = True
        previous_visible_rank = 30
        rank_delta = None (cannot compute when current is not visible)
        """
        timeline = [
            {"time": "09:00", "rank": 30},
            {"time": "09:30", "rank": None},
        ]
        stats = [{"word": "g", "titles": [_make_hotlist_item(
            rank_timeline=timeline, ranks=[30],
        )], "count": 1, "position": 0}]
        item = adapt_hotlist_stats(stats, context=_ctx(mode="current"))[0].source_items[0]
        self.assertEqual(item.normalized_rank, 30)
        self.assertIsNone(item.current_rank)
        self.assertTrue(item.previous_observation_exists)
        self.assertTrue(item.previous_observation_visible)
        self.assertEqual(item.previous_visible_rank, 30)
        self.assertIsNone(item.rank_delta)

    def test_no_reliable_timeline_fallback(self):
        """Case 3: no reliable timeline → current_rank falls back to normalized_rank.

        rank_timeline = []
        ranks = [10]
        normalized_rank = 10
        current_rank = 10 (fallback)
        has_reliable_rank_timeline = False
        rank_delta = None
        """
        stats = [{"word": "g", "titles": [_make_hotlist_item(
            rank_timeline=[], ranks=[10],
        )], "count": 1, "position": 0}]
        item = adapt_hotlist_stats(stats, context=_ctx(mode="current"))[0].source_items[0]
        self.assertEqual(item.normalized_rank, 10)
        self.assertEqual(item.current_rank, 10)  # fallback
        self.assertFalse(item.has_reliable_rank_timeline)
        self.assertIsNone(item.rank_delta)


# ---------------------------------------------------------------------------
# first_crawl_of_day and is_new_semantics
# ---------------------------------------------------------------------------


class TestFirstCrawlOfDay(unittest.TestCase):
    """Design §8.7: first_crawl_of_day guard for New Burst."""

    def test_context_first_crawl_preserved(self):
        stats = [{"word": "g", "titles": [_make_hotlist_item(is_new=True)], "count": 1, "position": 0}]
        ctx = CRRunContext(mode="incremental", first_crawl_of_day=True)
        item = adapt_hotlist_stats(stats, context=ctx)[0].source_items[0]
        self.assertTrue(item.first_crawl_of_day)

    def test_first_crawl_is_new_semantics(self):
        """first_crawl_of_day=true + is_new=true → incremental_first_crawl."""
        stats = [{"word": "g", "titles": [_make_hotlist_item(is_new=True)], "count": 1, "position": 0}]
        ctx = CRRunContext(mode="incremental", first_crawl_of_day=True)
        item = adapt_hotlist_stats(stats, context=ctx)[0].source_items[0]
        self.assertEqual(item.is_new_semantics, "incremental_first_crawl")

    def test_normal_new_titles_detection(self):
        """is_new=true, not first crawl → new_titles_detection."""
        stats = [{"word": "g", "titles": [_make_hotlist_item(is_new=True)], "count": 1, "position": 0}]
        ctx = CRRunContext(mode="current", first_crawl_of_day=False)
        item = adapt_hotlist_stats(stats, context=ctx)[0].source_items[0]
        self.assertEqual(item.is_new_semantics, "new_titles_detection")

    def test_not_new_semantics_unknown(self):
        """is_new=false → semantics don't matter, returns unknown."""
        stats = [{"word": "g", "titles": [_make_hotlist_item(is_new=False)], "count": 1, "position": 0}]
        item = adapt_hotlist_stats(stats, context=_ctx())[0].source_items[0]
        self.assertEqual(item.is_new_semantics, "unknown")

    def test_is_new_none(self):
        """is_new=None → unknown."""
        stats = [{"word": "g", "titles": [_make_hotlist_item(is_new=None)], "count": 1, "position": 0}]
        # Override to force None
        item_raw = _make_hotlist_item()
        item_raw["is_new"] = None
        stats = [{"word": "g", "titles": [item_raw], "count": 1, "position": 0}]
        item = adapt_hotlist_stats(stats, context=_ctx())[0].source_items[0]
        self.assertIsNone(item.is_new)
        self.assertEqual(item.is_new_semantics, "unknown")


# ---------------------------------------------------------------------------
# Synthetic time signals
# ---------------------------------------------------------------------------


class TestSyntheticTime(unittest.TestCase):
    """Design §8.6: incremental synthetic time must be flagged."""

    def test_incremental_same_first_last_synthetic(self):
        """incremental + first_time == last_time → time_signals_synthetic."""
        item_raw = _make_hotlist_item(first_time="10:00", last_time="10:00")
        stats = [{"word": "g", "titles": [item_raw], "count": 1, "position": 0}]
        item = adapt_hotlist_stats(stats, context=_ctx(mode="incremental"))[0].source_items[0]
        self.assertTrue(item.time_signals_synthetic)
        self.assertTrue(item.has_time_signals)

    def test_current_different_times_not_synthetic(self):
        item_raw = _make_hotlist_item(first_time="09:00", last_time="12:00")
        stats = [{"word": "g", "titles": [item_raw], "count": 1, "position": 0}]
        item = adapt_hotlist_stats(stats, context=_ctx(mode="current"))[0].source_items[0]
        self.assertFalse(item.time_signals_synthetic)
        self.assertTrue(item.has_time_signals)

    def test_no_time_signals(self):
        item_raw = _make_hotlist_item(first_time="", last_time="")
        stats = [{"word": "g", "titles": [item_raw], "count": 1, "position": 0}]
        item = adapt_hotlist_stats(stats, context=_ctx(mode="current"))[0].source_items[0]
        self.assertFalse(item.has_time_signals)


# ---------------------------------------------------------------------------
# Count semantics
# ---------------------------------------------------------------------------


class TestCountSemantics(unittest.TestCase):
    """Design §8.8: count must have explicit semantics."""

    def test_hotlist_count_is_crawl_count(self):
        stats = [{"word": "g", "titles": [_make_hotlist_item(count=5)], "count": 1, "position": 0}]
        item = adapt_hotlist_stats(stats, context=_ctx())[0].source_items[0]
        self.assertTrue(item.has_count)
        self.assertEqual(item.count, 5)
        self.assertEqual(item.count_semantics, "crawl_count")

    def test_rss_count_is_rss_item_count(self):
        stats = [{"word": "g", "titles": [_make_rss_item(count=1)], "count": 1, "position": 0}]
        item = adapt_rss_stats(stats, context=_ctx())[0].source_items[0]
        self.assertTrue(item.has_count)
        self.assertEqual(item.count_semantics, "rss_item_count")

    def test_count_zero_no_count(self):
        stats = [{"word": "g", "titles": [_make_hotlist_item(count=0)], "count": 1, "position": 0}]
        item = adapt_hotlist_stats(stats, context=_ctx())[0].source_items[0]
        self.assertFalse(item.has_count)
        self.assertEqual(item.count_semantics, "unknown")

    def test_count_none_no_count(self):
        item_raw = _make_hotlist_item()
        item_raw["count"] = None
        stats = [{"word": "g", "titles": [item_raw], "count": 1, "position": 0}]
        item = adapt_hotlist_stats(stats, context=_ctx())[0].source_items[0]
        self.assertFalse(item.has_count)


# ---------------------------------------------------------------------------
# Primitive record creation
# ---------------------------------------------------------------------------


class TestPrimitiveRecord(unittest.TestCase):
    """Design §5.2: primitive record groups source items."""

    def test_keyword_group_preserved(self):
        stats = [{"word": "AI前沿模型", "titles": [_make_hotlist_item()], "count": 1, "position": 0}]
        records = adapt_hotlist_stats(stats, context=_ctx())
        self.assertEqual(records[0].keyword_group, "AI前沿模型")

    def test_source_items_list_created(self):
        t1 = _make_hotlist_item(title="Title A")
        t2 = _make_hotlist_item(title="Title B")
        stats = [{"word": "g", "titles": [t1, t2], "count": 2, "position": 0}]
        records = adapt_hotlist_stats(stats, context=_ctx())
        self.assertEqual(len(records[0].source_items), 2)
        self.assertEqual(records[0].source_items[0].title, "Title A")
        self.assertEqual(records[0].source_items[1].title, "Title B")

    def test_primary_title_first_item(self):
        t1 = _make_hotlist_item(title="First")
        t2 = _make_hotlist_item(title="Second")
        stats = [{"word": "g", "titles": [t1, t2], "count": 2, "position": 0}]
        records = adapt_hotlist_stats(stats, context=_ctx())
        self.assertEqual(records[0].primary_title, "First")

    def test_representative_url_first_item(self):
        t1 = _make_hotlist_item(url="https://a.com")
        t2 = _make_hotlist_item(url="https://b.com")
        stats = [{"word": "g", "titles": [t1, t2], "count": 2, "position": 0}]
        records = adapt_hotlist_stats(stats, context=_ctx())
        self.assertEqual(records[0].representative_url, "https://a.com")

    def test_record_source_hotlist(self):
        stats = [{"word": "g", "titles": [_make_hotlist_item()], "count": 1, "position": 0}]
        records = adapt_hotlist_stats(stats, context=_ctx())
        self.assertEqual(records[0].record_source, "hotlist_stats")

    def test_record_source_rss(self):
        stats = [{"word": "g", "titles": [_make_rss_item()], "count": 1, "position": 0}]
        records = adapt_rss_stats(stats, context=_ctx())
        self.assertEqual(records[0].record_source, "rss_stats")

    def test_empty_group_skipped(self):
        stats = [{"word": "g", "titles": [], "count": 0, "position": 0}]
        records = adapt_hotlist_stats(stats, context=_ctx())
        self.assertEqual(len(records), 0)


# ---------------------------------------------------------------------------
# No scoring / decision fields
# ---------------------------------------------------------------------------


class TestNoScoringFields(unittest.TestCase):
    """PR9b must NOT produce scoring / decision fields."""

    def test_source_item_no_score_fields(self):
        stats = [{"word": "g", "titles": [_make_hotlist_item()], "count": 1, "position": 0}]
        item = adapt_hotlist_stats(stats, context=_ctx())[0].source_items[0]
        self.assertFalse(hasattr(item, "total_score"))
        self.assertFalse(hasattr(item, "growth_raw"))
        self.assertFalse(hasattr(item, "heat_score"))
        self.assertFalse(hasattr(item, "decision"))

    def test_primitive_record_no_score_fields(self):
        stats = [{"word": "g", "titles": [_make_hotlist_item()], "count": 1, "position": 0}]
        record = adapt_hotlist_stats(stats, context=_ctx())[0]
        self.assertFalse(hasattr(record, "total_score"))
        self.assertFalse(hasattr(record, "growth_raw"))
        self.assertFalse(hasattr(record, "decision"))

    def test_no_decision_field_on_record(self):
        stats = [{"word": "g", "titles": [_make_hotlist_item()], "count": 1, "position": 0}]
        record = adapt_hotlist_stats(stats, context=_ctx())[0]
        self.assertFalse(hasattr(record, "cr_decision"))


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------


class TestEdgeCases(unittest.TestCase):
    """Various edge cases."""

    def test_multiple_keyword_groups(self):
        g1 = {"word": "AI", "titles": [_make_hotlist_item(title="AI Title")], "count": 1, "position": 0}
        g2 = {"word": "Finance", "titles": [_make_hotlist_item(title="Fin Title")], "count": 1, "position": 1}
        records = adapt_hotlist_stats([g1, g2], context=_ctx())
        self.assertEqual(len(records), 2)
        self.assertEqual(records[0].keyword_group, "AI")
        self.assertEqual(records[1].keyword_group, "Finance")

    def test_rss_empty_stats(self):
        records = adapt_rss_stats([], context=_ctx())
        self.assertEqual(len(records), 0)

    def test_hotlist_empty_stats(self):
        records = adapt_hotlist_stats([], context=_ctx())
        self.assertEqual(len(records), 0)

    def test_context_defaults(self):
        ctx = CRRunContext()
        self.assertEqual(ctx.mode, "unknown")
        self.assertIsNone(ctx.run_time)
        self.assertIsNone(ctx.first_crawl_of_day)

    def test_source_item_url_fallback_to_mobile(self):
        """If url is empty, try mobileUrl."""
        item_raw = _make_hotlist_item(url="", )
        item_raw["mobileUrl"] = "https://m.example.com"
        stats = [{"word": "g", "titles": [item_raw], "count": 1, "position": 0}]
        item = adapt_hotlist_stats(stats, context=_ctx())[0].source_items[0]
        self.assertEqual(item.url, "https://m.example.com")

    def test_rss_source_id_is_none(self):
        """RSS items don't have source_id (hotlist concept)."""
        stats = [{"word": "g", "titles": [_make_rss_item()], "count": 1, "position": 0}]
        item = adapt_rss_stats(stats, context=_ctx())[0].source_items[0]
        self.assertIsNone(item.source_id)

    def test_current_hotlist_item_from_recovered_source_is_marked(self):
        raw = _make_hotlist_item(
            title="Recovered event",
            source_id="weibo",
            is_new=True,
        )
        identity = input_item_identity(
            source_type="hotlist",
            source_id="weibo",
            title="Recovered event",
        )
        health = evaluate_cr_input_health(
            hotlist_successful_ids=("weibo",),
            hotlist_recovered_ids=("weibo",),
            recovery_state_status="tracked",
        )
        context = CRRunContext(
            mode="current",
            first_crawl_of_day=False,
            observed_item_identities=frozenset((identity,)),
            input_health=health,
        )
        item = adapt_hotlist_stats(
            [{"word": "g", "titles": [raw]}],
            context=context,
        )[0].source_items[0]
        self.assertTrue(item.observed_in_current_run)
        self.assertTrue(item.observed_after_ingest_gap)

    def test_historical_item_from_recovered_source_is_not_marked(self):
        health = evaluate_cr_input_health(
            hotlist_successful_ids=("weibo",),
            hotlist_recovered_ids=("weibo",),
            recovery_state_status="tracked",
        )
        item = adapt_hotlist_stats(
            [{"word": "g", "titles": [_make_hotlist_item(source_id="weibo")]}],
            context=CRRunContext(mode="current", input_health=health),
        )[0].source_items[0]
        self.assertFalse(item.observed_in_current_run)
        self.assertFalse(item.observed_after_ingest_gap)

    def test_current_rss_item_from_recovered_feed_is_marked(self):
        raw = _make_rss_item(
            title="Recovered RSS event",
            feed_id="feed-a",
        )
        raw["precomputed_entities"] = ["entity-a", "entity-b"]
        identity = input_item_identity(
            source_type="rss",
            feed_id="feed-a",
            title="Recovered RSS event",
            url=raw["url"],
        )
        health = evaluate_cr_input_health(
            rss_successful_ids=("feed-a",),
            rss_recovered_ids=("feed-a",),
            recovery_state_status="tracked",
        )
        item = adapt_rss_stats(
            [{"word": "g", "titles": [raw]}],
            context=CRRunContext(
                mode="current",
                observed_item_identities=frozenset((identity,)),
                input_health=health,
            ),
        )[0].source_items[0]
        self.assertTrue(item.observed_in_current_run)
        self.assertTrue(item.observed_after_ingest_gap)
        self.assertEqual(
            item.precomputed_entities,
            frozenset({"entity-a", "entity-b"}),
        )


if __name__ == "__main__":
    unittest.main()
