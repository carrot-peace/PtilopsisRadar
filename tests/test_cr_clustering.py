# coding=utf-8
"""
PR9c: CR deterministic topic clustering tests.

Covers:
  A. Normalization (punctuation, whitespace, full/half-width, CJK, empty)
  B. Exact clustering (title match, URL match, unrelated titles)
  C. Keyword group safety (same group alone does NOT merge)
  D. Hotlist + RSS merge (same title, similar title, pseudo-rank isolation)
  E. Display title (hotlist beats RSS, rank priority, RSS-only fallback)
  F. Candidate aggregate fields (dedup, flags, rank aggregates)
  G. Stable ID (input order independence, determinism)
  H. No scoring (CRCandidate has no score/decision fields)
"""

import os
import sys
import unittest

# Ensure project root is on path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from trendradar.cr.models import (
    CRCandidate,
    CRClusterConfig,
    CRPrimitiveRecord,
    CRSourceItem,
)
from trendradar.cr.cluster import (
    build_candidate_from_cluster,
    build_cr_candidates,
    extract_topic_tokens,
    normalize_topic_text,
    title_similarity,
)
from trendradar.cr.entity_match import (
    EntityResources,
    clear_entity_resources_cache,
    extract_entities,
    is_high_specificity,
    load_entity_resources,
)
from trendradar.cr.scoring import score_cr_candidate, score_cross_layer_raw

try:
    import yaml as _yaml  # noqa: F401
    _HAS_YAML = True
except ImportError:
    _HAS_YAML = False


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _hotlist_item(
    title="Test Title",
    source_name="weibo",
    source_id="weibo",
    url="https://example.com/1",
    keyword_group="AI",
    current_rank=10,
    normalized_rank=5,
    count=3,
) -> CRSourceItem:
    """Build a hotlist CRSourceItem for testing."""
    return CRSourceItem(
        source_type="hotlist",
        source_id=source_id,
        source_name=source_name,
        title=title,
        url=url,
        keyword_group=keyword_group,
        keyword_groups=[keyword_group] if keyword_group else None,
        current_rank=current_rank,
        normalized_rank=normalized_rank,
        is_visible=current_rank is not None,
        count=count,
        has_count=count is not None and count > 0,
    )


def _rss_item(
    title="RSS Title",
    source_name="Hacker News",
    feed_id="hacker-news",
    url="https://hn.example.com/1",
    keyword_group="AI",
    published_at="2026-06-08T08:00:00+08:00",
) -> CRSourceItem:
    """Build an RSS CRSourceItem for testing."""
    return CRSourceItem(
        source_type="rss",
        source_name=source_name,
        feed_id=feed_id,
        title=title,
        url=url,
        keyword_group=keyword_group,
        keyword_groups=[keyword_group] if keyword_group else None,
        current_rank=None,
        normalized_rank=None,
        is_visible=False,
        published_at=published_at,
    )


def _primitive_record(
    keyword_group="AI",
    source_items=None,
) -> CRPrimitiveRecord:
    """Build a CRPrimitiveRecord for testing."""
    if source_items is None:
        source_items = [_hotlist_item()]
    return CRPrimitiveRecord(
        keyword_group=keyword_group,
        keyword_groups=[keyword_group] if keyword_group else [],
        source_items=source_items,
    )


# ---------------------------------------------------------------------------
# A. Normalization
# ---------------------------------------------------------------------------


class TestNormalizeTopicText(unittest.TestCase):
    """A. Text normalization for deterministic comparison."""

    def test_punctuation_removed(self):
        result = normalize_topic_text("Hello, World! Test.")
        self.assertNotIn(",", result)
        self.assertNotIn("!", result)
        self.assertNotIn(".", result)
        self.assertIn("hello", result)
        self.assertIn("world", result)

    def test_whitespace_collapsed(self):
        result = normalize_topic_text("Hello   World\tTest")
        self.assertEqual(result, "hello world test")

    def test_fullwidth_to_halfwidth(self):
        """NFKC normalizes full-width ASCII to half-width."""
        # Full-width 'Ｈｅｌｌｏ' → 'hello'
        result = normalize_topic_text("Ｈｅｌｌｏ")
        self.assertEqual(result, "hello")

    def test_english_lowercased(self):
        result = normalize_topic_text("OpenAI GPT-5 Release")
        self.assertIn("openai", result)
        self.assertEqual(result, "openai gpt 5 release")

    def test_empty_string(self):
        self.assertEqual(normalize_topic_text(""), "")

    def test_whitespace_only(self):
        self.assertEqual(normalize_topic_text("   "), "")

    def test_none_like_empty(self):
        """Empty string input returns empty string."""
        self.assertEqual(normalize_topic_text(""), "")


class TestExtractTopicTokens(unittest.TestCase):
    """A. Token extraction for English and CJK text."""

    def test_english_word_tokens(self):
        tokens = extract_topic_tokens("OpenAI GPT-5 Release")
        self.assertIn("openai", tokens)
        self.assertIn("gpt", tokens)
        self.assertIn("5", tokens)
        self.assertIn("release", tokens)

    def test_cjk_has_tokens(self):
        tokens = extract_topic_tokens("人工智能最新进展")
        # Should produce bigrams
        self.assertTrue(len(tokens) > 0)

    def test_cjk_bigrams_present(self):
        tokens = extract_topic_tokens("人工智能")
        # Expected bigrams: 人工, 工智, 智能
        self.assertIn("人工", tokens)
        self.assertIn("工智", tokens)
        self.assertIn("智能", tokens)

    def test_empty_title_safe(self):
        tokens = extract_topic_tokens("")
        self.assertEqual(tokens, set())

    def test_whitespace_only_safe(self):
        tokens = extract_topic_tokens("   ")
        self.assertEqual(tokens, set())

    def test_mixed_cjk_english(self):
        tokens = extract_topic_tokens("AI人工智能")
        # Should have "ai" and CJK bigrams
        self.assertIn("ai", tokens)
        self.assertTrue(len(tokens) > 1)

    def test_punctuation_stripped(self):
        tokens = extract_topic_tokens("Hello, World!")
        self.assertIn("hello", tokens)
        self.assertIn("world", tokens)


class TestTitleSimilarity(unittest.TestCase):
    """A. Title similarity metric."""

    def test_identical_titles(self):
        sim = title_similarity("OpenAI Release", "OpenAI Release")
        self.assertAlmostEqual(sim, 1.0)

    def test_similar_titles(self):
        sim = title_similarity("OpenAI GPT-5 Release", "OpenAI GPT-5 New Model")
        # shared: openai, gpt, 5 → 3 tokens; min size = 3 (openai, gpt, 5) vs 4
        self.assertGreater(sim, 0.5)

    def test_unrelated_titles(self):
        sim = title_similarity("OpenAI GPT-5", "天气预报 今日晴")
        self.assertAlmostEqual(sim, 0.0)

    def test_empty_title_returns_zero(self):
        self.assertAlmostEqual(title_similarity("", "Hello"), 0.0)
        self.assertAlmostEqual(title_similarity("Hello", ""), 0.0)
        self.assertAlmostEqual(title_similarity("", ""), 0.0)


# ---------------------------------------------------------------------------
# B. Exact clustering
# ---------------------------------------------------------------------------


class TestExactClustering(unittest.TestCase):
    """B. Exact title / URL merge; unrelated titles do not merge."""

    def test_exact_same_normalized_title_merges(self):
        """Same normalized title → same cluster."""
        items = [
            _hotlist_item(title="OpenAI 发布新模型", url="https://a.com/1"),
            _hotlist_item(title="OpenAI 发布新模型", url="https://a.com/2"),
        ]
        config = CRClusterConfig()
        clusters = _cluster(items, config)
        self.assertEqual(len(clusters), 1)

    def test_exact_same_url_merges(self):
        """Same URL → same cluster, even if titles differ slightly."""
        items = [
            _hotlist_item(title="OpenAI 发布新模型", url="https://example.com/same"),
            _hotlist_item(title="OpenAI发布新模型", url="https://example.com/same"),
        ]
        config = CRClusterConfig()
        clusters = _cluster(items, config)
        self.assertEqual(len(clusters), 1)

    def test_different_unrelated_titles_do_not_merge(self):
        """Unrelated titles → separate clusters."""
        items = [
            _hotlist_item(title="OpenAI 发布新模型", url="https://a.com/1"),
            _hotlist_item(title="今日天气预报晴", url="https://b.com/1"),
        ]
        config = CRClusterConfig()
        clusters = _cluster(items, config)
        self.assertEqual(len(clusters), 2)

    def test_similar_title_token_overlap_merges(self):
        """Titles with sufficient token overlap → merge."""
        items = [
            _hotlist_item(title="OpenAI 发布 GPT-5 新模型"),
            _hotlist_item(title="OpenAI 发布 GPT-5 最新进展"),
        ]
        config = CRClusterConfig(min_shared_tokens=2, min_similarity=0.5)
        clusters = _cluster(items, config)
        self.assertEqual(len(clusters), 1)


# Internal helper imported intentionally to test clustering invariants.
from trendradar.cr.cluster import _cluster_source_items


def _cluster(items, config):
    """Helper to call _cluster_source_items and return clusters."""
    return _cluster_source_items(items, config)


# ---------------------------------------------------------------------------
# C. Keyword group safety
# ---------------------------------------------------------------------------


class TestKeywordGroupSafety(unittest.TestCase):
    """C. Same keyword_group alone must NOT merge unrelated titles."""

    def test_same_keyword_group_unrelated_titles_no_merge(self):
        """keyword_group='AI' alone does NOT merge unrelated titles."""
        items = [
            _hotlist_item(title="OpenAI 发布新模型", keyword_group="AI", url="https://a.com/1"),
            _hotlist_item(title="某地 AI 诈骗案件", keyword_group="AI", url="https://b.com/1"),
        ]
        config = CRClusterConfig()
        clusters = _cluster(items, config)
        self.assertEqual(len(clusters), 2)

    def test_same_keyword_group_similar_titles_can_merge(self):
        """Same keyword_group + similar titles → merge (by title overlap, not group)."""
        items = [
            _hotlist_item(title="OpenAI 发布 GPT-5 新模型", keyword_group="AI"),
            _hotlist_item(title="OpenAI 发布 GPT-5 最新进展", keyword_group="AI"),
        ]
        config = CRClusterConfig(min_shared_tokens=2, min_similarity=0.5)
        clusters = _cluster(items, config)
        self.assertEqual(len(clusters), 1)

    def test_different_keyword_groups_same_title_merge(self):
        """Same title in different keyword groups → still merge (by title, not group)."""
        items = [
            _hotlist_item(title="OpenAI 发布新模型", keyword_group="AI"),
            _hotlist_item(title="OpenAI 发布新模型", keyword_group="Tech"),
        ]
        config = CRClusterConfig()
        clusters = _cluster(items, config)
        self.assertEqual(len(clusters), 1)


# ---------------------------------------------------------------------------
# D. Hotlist + RSS merge
# ---------------------------------------------------------------------------


class TestHotlistRSSMerge(unittest.TestCase):
    """D. Hotlist and RSS items merge when titles match."""

    def test_hotlist_rss_same_title_merge(self):
        """Hotlist + RSS with same title → one cluster."""
        items = [
            _hotlist_item(title="OpenAI 发布新模型", url="https://a.com/1"),
            _rss_item(title="OpenAI 发布新模型", url="https://b.com/1"),
        ]
        config = CRClusterConfig()
        clusters = _cluster(items, config)
        self.assertEqual(len(clusters), 1)

    def test_hotlist_rss_similar_title_merge(self):
        """Hotlist + RSS with similar title → merge if token overlap sufficient."""
        items = [
            _hotlist_item(title="OpenAI 发布 GPT-5 新模型"),
            _rss_item(title="OpenAI 发布 GPT-5 最新报道"),
        ]
        config = CRClusterConfig(min_shared_tokens=2, min_similarity=0.5)
        clusters = _cluster(items, config)
        self.assertEqual(len(clusters), 1)

    def test_rss_pseudo_rank_does_not_affect_best_rank(self):
        """RSS pseudo-rank must NOT influence candidate best rank fields."""
        items = [
            _hotlist_item(
                title="Same Title",
                current_rank=10,
                normalized_rank=5,
            ),
            _rss_item(title="Same Title"),
        ]
        candidate = build_candidate_from_cluster(items, CRClusterConfig())
        # Best ranks come from hotlist only.
        self.assertEqual(candidate.best_current_rank, 10)
        self.assertEqual(candidate.best_normalized_rank, 5)

    def test_rss_only_candidate_no_rank(self):
        """RSS-only candidate has no rank fields."""
        items = [
            _rss_item(title="RSS Only Title"),
        ]
        candidate = build_candidate_from_cluster(items, CRClusterConfig())
        self.assertIsNone(candidate.best_current_rank)
        self.assertIsNone(candidate.best_normalized_rank)
        self.assertTrue(candidate.has_rss)
        self.assertFalse(candidate.has_hotlist)


# ---------------------------------------------------------------------------
# E. Display title
# ---------------------------------------------------------------------------


class TestDisplayTitle(unittest.TestCase):
    """E. Display title selection: heat-first, deterministic."""

    def test_hotlist_beats_rss(self):
        """Hotlist title wins over RSS title when both in cluster."""
        items = [
            _rss_item(title="RSS Version Of Title"),
            _hotlist_item(title="Hotlist Version Of Title", current_rank=5),
        ]
        candidate = build_candidate_from_cluster(items, CRClusterConfig())
        self.assertEqual(candidate.display_title, "Hotlist Version Of Title")

    def test_better_current_rank_wins(self):
        """Lower (better) current_rank wins display title."""
        items = [
            _hotlist_item(title="Title A", current_rank=20, normalized_rank=10),
            _hotlist_item(title="Title B", current_rank=5, normalized_rank=5),
        ]
        candidate = build_candidate_from_cluster(items, CRClusterConfig())
        self.assertEqual(candidate.display_title, "Title B")

    def test_normalized_rank_fallback(self):
        """If no reliable current_rank, normalized_rank guides selection."""
        items = [
            _hotlist_item(title="Title A", current_rank=None, normalized_rank=20),
            _hotlist_item(title="Title B", current_rank=None, normalized_rank=5),
        ]
        candidate = build_candidate_from_cluster(items, CRClusterConfig())
        self.assertEqual(candidate.display_title, "Title B")

    def test_rss_only_stable_display_title(self):
        """RSS-only candidate has a stable (non-empty) display title."""
        items = [
            _rss_item(title="RSS Only Title"),
        ]
        candidate = build_candidate_from_cluster(items, CRClusterConfig())
        self.assertEqual(candidate.display_title, "RSS Only Title")

    def test_count_as_tiebreaker(self):
        """When ranks and source_type are equal, higher count wins."""
        items = [
            _hotlist_item(title="Low Count", current_rank=10, normalized_rank=5, count=1),
            _hotlist_item(title="High Count", current_rank=10, normalized_rank=5, count=10),
        ]
        candidate = build_candidate_from_cluster(items, CRClusterConfig())
        self.assertEqual(candidate.display_title, "High Count")

    def test_normalized_title_final_tiebreaker(self):
        """When all rank/count fields are equal, normalized title decides."""
        items = [
            _hotlist_item(
                title="Zebra News", current_rank=10, normalized_rank=5, count=3,
                url="https://z.com", source_id="z", source_name="z",
            ),
            _hotlist_item(
                title="Apple News", current_rank=10, normalized_rank=5, count=3,
                url="https://a.com", source_id="a", source_name="a",
            ),
        ]
        candidate = build_candidate_from_cluster(items, CRClusterConfig())
        # "apple news" < "zebra news" lexicographically.
        self.assertEqual(candidate.display_title, "Apple News")

    def test_display_title_stable_under_input_order(self):
        """display_title is the same regardless of input order."""
        items_fwd = [
            _hotlist_item(title="Zebra", current_rank=10, normalized_rank=5, count=3),
            _hotlist_item(title="Apple", current_rank=10, normalized_rank=5, count=3),
        ]
        items_rev = list(reversed(items_fwd))
        cand_fwd = build_candidate_from_cluster(items_fwd, CRClusterConfig())
        cand_rev = build_candidate_from_cluster(items_rev, CRClusterConfig())
        self.assertEqual(cand_fwd.display_title, cand_rev.display_title)
        self.assertEqual(cand_fwd.display_title, "Apple")

    def test_rss_only_display_title_deterministic(self):
        """RSS-only cluster picks a stable display title by normalized title."""
        items_fwd = [
            _rss_item(title="Zebra RSS"),
            _rss_item(title="Apple RSS"),
        ]
        items_rev = list(reversed(items_fwd))
        cand_fwd = build_candidate_from_cluster(items_fwd, CRClusterConfig())
        cand_rev = build_candidate_from_cluster(items_rev, CRClusterConfig())
        self.assertEqual(cand_fwd.display_title, cand_rev.display_title)
        self.assertEqual(cand_fwd.display_title, "Apple RSS")


# ---------------------------------------------------------------------------
# F. Candidate aggregate fields
# ---------------------------------------------------------------------------


class TestCandidateAggregates(unittest.TestCase):
    """F. Aggregate fields: dedup, flags, rank fields."""

    def test_keyword_groups_deduplicated(self):
        """keyword_groups are deduplicated across cluster items."""
        items = [
            _hotlist_item(title="Title A", keyword_group="AI"),
            _hotlist_item(title="Title B", keyword_group="AI"),
            _rss_item(title="Title C", keyword_group="Tech"),
        ]
        # Force merge via same URL.
        for it in items:
            it.url = "https://same.url"
        candidate = build_candidate_from_cluster(items, CRClusterConfig())
        self.assertIn("AI", candidate.keyword_groups)
        self.assertIn("Tech", candidate.keyword_groups)
        # "AI" appears only once despite two items.
        self.assertEqual(candidate.keyword_groups.count("AI"), 1)

    def test_source_names_deduplicated(self):
        """source_names are deduplicated."""
        items = [
            _hotlist_item(title="Title A", source_name="weibo"),
            _hotlist_item(title="Title B", source_name="weibo"),
        ]
        for it in items:
            it.url = "https://same.url"
        candidate = build_candidate_from_cluster(items, CRClusterConfig())
        self.assertEqual(candidate.source_names.count("weibo"), 1)

    def test_has_hotlist_and_has_rss(self):
        """Flags are correct for mixed cluster."""
        items = [
            _hotlist_item(title="Title A"),
            _rss_item(title="Title B"),
        ]
        for it in items:
            it.url = "https://same.url"
        candidate = build_candidate_from_cluster(items, CRClusterConfig())
        self.assertTrue(candidate.has_hotlist)
        self.assertTrue(candidate.has_rss)

    def test_best_current_rank_from_hotlist(self):
        """best_current_rank = min current_rank among hotlist items."""
        items = [
            _hotlist_item(title="A", current_rank=20, normalized_rank=10),
            _hotlist_item(title="B", current_rank=5, normalized_rank=3),
        ]
        for it in items:
            it.url = "https://same.url"
        candidate = build_candidate_from_cluster(items, CRClusterConfig())
        self.assertEqual(candidate.best_current_rank, 5)

    def test_best_normalized_rank_from_hotlist(self):
        """best_normalized_rank = min normalized_rank among hotlist items."""
        items = [
            _hotlist_item(title="A", current_rank=20, normalized_rank=10),
            _hotlist_item(title="B", current_rank=5, normalized_rank=3),
        ]
        for it in items:
            it.url = "https://same.url"
        candidate = build_candidate_from_cluster(items, CRClusterConfig())
        self.assertEqual(candidate.best_normalized_rank, 3)

    def test_primary_source_type_hotlist(self):
        items = [_hotlist_item(title="A")]
        candidate = build_candidate_from_cluster(items, CRClusterConfig())
        self.assertEqual(candidate.primary_source_type, "hotlist")

    def test_primary_source_type_rss(self):
        items = [_rss_item(title="A")]
        candidate = build_candidate_from_cluster(items, CRClusterConfig())
        self.assertEqual(candidate.primary_source_type, "rss")

    def test_primary_source_type_mixed(self):
        items = [
            _hotlist_item(title="A"),
            _rss_item(title="B"),
        ]
        for it in items:
            it.url = "https://same.url"
        candidate = build_candidate_from_cluster(items, CRClusterConfig())
        self.assertEqual(candidate.primary_source_type, "mixed")

    def test_rss_items_excluded_from_best_rank(self):
        """RSS items should not affect best_normalized_rank / best_current_rank."""
        items = [
            _hotlist_item(title="A", current_rank=15, normalized_rank=10),
            _rss_item(title="B"),  # RSS has no rank
        ]
        for it in items:
            it.url = "https://same.url"
        candidate = build_candidate_from_cluster(items, CRClusterConfig())
        self.assertEqual(candidate.best_current_rank, 15)
        self.assertEqual(candidate.best_normalized_rank, 10)


# ---------------------------------------------------------------------------
# G. Stable ID
# ---------------------------------------------------------------------------


class TestStableID(unittest.TestCase):
    """G. candidate_id and cluster_key are deterministic."""

    def test_same_items_different_order_same_id(self):
        """Same source items in different input order → same candidate_id."""
        items_a = [
            _hotlist_item(title="Title A", url="https://a.com"),
            _hotlist_item(title="Title B", url="https://b.com"),
        ]
        items_b = list(reversed(items_a))

        cand_a = build_candidate_from_cluster(items_a, CRClusterConfig())
        cand_b = build_candidate_from_cluster(items_b, CRClusterConfig())

        self.assertEqual(cand_a.candidate_id, cand_b.candidate_id)
        self.assertEqual(cand_a.cluster_key, cand_b.cluster_key)

    def test_cluster_key_stable(self):
        """cluster_key is deterministic for the same cluster."""
        items = [
            _hotlist_item(title="Title A", url="https://a.com"),
            _hotlist_item(title="Title B", url="https://b.com"),
        ]
        c1 = build_candidate_from_cluster(items, CRClusterConfig())
        c2 = build_candidate_from_cluster(items, CRClusterConfig())
        self.assertEqual(c1.cluster_key, c2.cluster_key)

    def test_candidate_id_not_empty(self):
        """candidate_id is always a non-empty string."""
        items = [_hotlist_item(title="Title")]
        candidate = build_candidate_from_cluster(items, CRClusterConfig())
        self.assertTrue(candidate.candidate_id)
        self.assertIsInstance(candidate.candidate_id, str)
        # SHA1 hex prefix of length 12.
        self.assertEqual(len(candidate.candidate_id), 12)

    def test_different_clusters_different_ids(self):
        """Different clusters produce different candidate_ids."""
        items_a = [_hotlist_item(title="Title A", url="https://a.com")]
        items_b = [_hotlist_item(title="Completely Different", url="https://b.com")]
        cand_a = build_candidate_from_cluster(items_a, CRClusterConfig())
        cand_b = build_candidate_from_cluster(items_b, CRClusterConfig())
        self.assertNotEqual(cand_a.candidate_id, cand_b.candidate_id)

    def test_full_stability_under_input_order(self):
        """Same items in different order → same candidate count, titles, IDs, display_title."""
        items_fwd = [
            _hotlist_item(title="Topic Alpha", url="https://a.com/1", keyword_group="AI"),
            _hotlist_item(title="Topic Beta", url="https://b.com/1", keyword_group="AI"),
            _rss_item(title="Topic Alpha RSS", url="https://c.com/1", keyword_group="Tech"),
        ]
        items_rev = list(reversed(items_fwd))

        r_fwd = [_primitive_record(source_items=items_fwd)]
        r_rev = [_primitive_record(source_items=items_rev)]

        cands_fwd = build_cr_candidates(r_fwd)
        cands_rev = build_cr_candidates(r_rev)

        # Same number of candidates.
        self.assertEqual(len(cands_fwd), len(cands_rev))

        # Same candidate IDs.
        ids_fwd = [c.candidate_id for c in cands_fwd]
        ids_rev = [c.candidate_id for c in cands_rev]
        self.assertEqual(ids_fwd, ids_rev)

        # Same cluster keys.
        keys_fwd = [c.cluster_key for c in cands_fwd]
        keys_rev = [c.cluster_key for c in cands_rev]
        self.assertEqual(keys_fwd, keys_rev)

        # Same display titles.
        titles_fwd = [c.display_title for c in cands_fwd]
        titles_rev = [c.display_title for c in cands_rev]
        self.assertEqual(titles_fwd, titles_rev)

        # Same source item title sets per candidate (cluster membership).
        for cf, cr in zip(cands_fwd, cands_rev):
            item_titles_fwd = sorted(it.title for it in cf.source_items)
            item_titles_rev = sorted(it.title for it in cr.source_items)
            self.assertEqual(item_titles_fwd, item_titles_rev)

    def test_source_items_order_deterministic(self):
        """source_items list order is the same regardless of input order."""
        items_fwd = [
            _hotlist_item(title="Zebra", current_rank=20, normalized_rank=10, count=1),
            _hotlist_item(title="Apple", current_rank=5, normalized_rank=3, count=5),
            _hotlist_item(title="Middle", current_rank=10, normalized_rank=5, count=3),
        ]
        items_rev = list(reversed(items_fwd))

        cand_fwd = build_candidate_from_cluster(items_fwd, CRClusterConfig())
        cand_rev = build_candidate_from_cluster(items_rev, CRClusterConfig())

        titles_fwd = [it.title for it in cand_fwd.source_items]
        titles_rev = [it.title for it in cand_rev.source_items]
        self.assertEqual(titles_fwd, titles_rev)

    def test_empty_title_url_clusters_not_colliding(self):
        """Different clusters with all-empty titles/URLs get different candidate_ids."""
        # Two items with empty titles, empty URLs, but different source metadata.
        item_a = CRSourceItem(
            source_type="hotlist", source_id="weibo", source_name="weibo",
            title="", url=None, keyword_group="AI",
        )
        item_b = CRSourceItem(
            source_type="rss", feed_id="hacker-news", source_name="HN",
            title="", url=None, keyword_group="Tech",
        )
        # They won't merge (no title/URL/token overlap) → separate clusters.
        records = [_primitive_record(source_items=[item_a, item_b])]
        candidates = build_cr_candidates(records)
        self.assertEqual(len(candidates), 2)
        self.assertNotEqual(candidates[0].candidate_id, candidates[1].candidate_id)
        self.assertNotEqual(candidates[0].cluster_key, candidates[1].cluster_key)
        self.assertNotEqual(candidates[0].cluster_key, "empty")
        self.assertNotEqual(candidates[1].cluster_key, "empty")


# ---------------------------------------------------------------------------
# H. Transitive merge (chain similarity)
# ---------------------------------------------------------------------------


class TestTransitiveMerge(unittest.TestCase):
    """H. A↔B, B↔C, A↛C → all in one cluster (union-find transitivity)."""

    def test_chain_merge(self):
        """A similar B, B similar C, A not similar C → one cluster.

        We construct three titles where:
          - A and B share 3 tokens → merge.
          - B and C share 2 tokens → merge.
          - A and C share 1 token → no direct merge.
        Union-find transitivity puts all three in one cluster.
        """
        title_a = "alpha beta gamma report"
        title_b = "alpha beta gamma analysis"
        title_c = "gamma analysis delta update"

        # Verify A and C do NOT merge directly.
        sim_ac = title_similarity(title_a, title_c)
        self.assertLess(sim_ac, 0.55)

        # Verify A↔B and B↔C would merge.
        self.assertGreaterEqual(title_similarity(title_a, title_b), 0.5)
        self.assertGreaterEqual(title_similarity(title_b, title_c), 0.5)

        items = [
            _hotlist_item(title=title_a, url="https://a.com"),
            _hotlist_item(title=title_b, url="https://b.com"),
            _hotlist_item(title=title_c, url="https://c.com"),
        ]
        config = CRClusterConfig(min_shared_tokens=2, min_similarity=0.5)
        clusters = _cluster(items, config)

        # All three should be in one cluster due to transitivity.
        self.assertEqual(len(clusters), 1)
        self.assertEqual(len(clusters[0]), 3)


# ---------------------------------------------------------------------------
# I. Empty URL safety
# ---------------------------------------------------------------------------


class TestEmptyURLSafety(unittest.TestCase):
    """I. Empty / None URLs must NOT cause spurious merges."""

    def test_none_urls_unrelated_no_merge(self):
        """Two unrelated items with url=None should NOT merge."""
        items = [
            _hotlist_item(title="OpenAI 发布新模型", url=None),
            _hotlist_item(title="今日天气预报晴", url=None),
        ]
        config = CRClusterConfig()
        clusters = _cluster(items, config)
        self.assertEqual(len(clusters), 2)

    def test_empty_string_urls_unrelated_no_merge(self):
        """Two unrelated items with url="" should NOT merge."""
        items = [
            _hotlist_item(title="OpenAI 发布新模型", url=""),
            _hotlist_item(title="今日天气预报晴", url=""),
        ]
        config = CRClusterConfig()
        clusters = _cluster(items, config)
        self.assertEqual(len(clusters), 2)

    def test_mixed_none_empty_url_no_merge(self):
        """One None URL and one "" URL should NOT merge (both falsy)."""
        items = [
            _hotlist_item(title="Title A", url=None),
            _hotlist_item(title="Title B", url=""),
        ]
        config = CRClusterConfig()
        clusters = _cluster(items, config)
        # Different titles, no URL match → separate clusters.
        self.assertEqual(len(clusters), 2)

    def test_nonempty_url_merges(self):
        """Two items with same non-empty URL merge even with different titles."""
        items = [
            _hotlist_item(title="Title A", url="https://example.com/same"),
            _hotlist_item(title="Title B", url="https://example.com/same"),
        ]
        config = CRClusterConfig()
        clusters = _cluster(items, config)
        self.assertEqual(len(clusters), 1)


# ---------------------------------------------------------------------------
# J. CJK weak overlap safety
# ---------------------------------------------------------------------------


class TestCJKWeakOverlap(unittest.TestCase):
    """J. Short CJK titles with weak overlap must NOT over-merge."""

    def test_unrelated_chinese_titles_no_merge(self):
        """Completely unrelated Chinese titles → separate clusters."""
        items = [
            _hotlist_item(title="OpenAI 发布新模型", url="https://a.com/1"),
            _hotlist_item(title="某地 AI 诈骗案件", url="https://b.com/1"),
        ]
        config = CRClusterConfig()
        clusters = _cluster(items, config)
        self.assertEqual(len(clusters), 2)

    def test_weak_cjk_overlap_no_merge(self):
        """CJK titles sharing only 1 bigram below threshold → no merge.

        "AI技术新突破" tokens: ai, 技术, 术新, 新突, 突破
        "AI安全新挑战" tokens: ai, 安全, 全新, 新挑, 挑战
        Shared: {ai} → 1 token < min_shared_tokens=2.
        """
        items = [
            _hotlist_item(title="AI技术新突破", url="https://a.com/1"),
            _hotlist_item(title="AI安全新挑战", url="https://b.com/1"),
        ]
        config = CRClusterConfig(min_shared_tokens=2, min_similarity=0.55)
        clusters = _cluster(items, config)
        self.assertEqual(len(clusters), 2)

    def test_strong_cjk_overlap_merges(self):
        """CJK titles with strong overlap → merge (proving CJK merge is not blocked).

        "人工智能技术新突破" tokens include: 人工, 工智, 智能, 能技, 技术, 术新, 新突, 突破
        "人工智能技术最新进展" tokens include: 人工, 工智, 智能, 能技, 技术, 术最, 最新, 新进, 进展
        Shared: {人工, 工智, 智能, 能技, 技术} → 5 tokens, min_size = 8, sim = 5/8 = 0.625.
        """
        items = [
            _hotlist_item(title="人工智能技术新突破", url="https://a.com/1"),
            _hotlist_item(title="人工智能技术最新进展", url="https://b.com/1"),
        ]
        config = CRClusterConfig(min_shared_tokens=2, min_similarity=0.55)
        clusters = _cluster(items, config)
        self.assertEqual(len(clusters), 1)


class TestNoScoringFields(unittest.TestCase):
    """H. CRCandidate must NOT have scoring / decision fields."""

    def test_no_total_score(self):
        items = [_hotlist_item()]
        candidate = build_candidate_from_cluster(items, CRClusterConfig())
        self.assertFalse(hasattr(candidate, "total_score"))

    def test_no_growth_raw(self):
        items = [_hotlist_item()]
        candidate = build_candidate_from_cluster(items, CRClusterConfig())
        self.assertFalse(hasattr(candidate, "growth_raw"))

    def test_no_heat_score(self):
        items = [_hotlist_item()]
        candidate = build_candidate_from_cluster(items, CRClusterConfig())
        self.assertFalse(hasattr(candidate, "heat_score"))

    def test_no_decision(self):
        items = [_hotlist_item()]
        candidate = build_candidate_from_cluster(items, CRClusterConfig())
        self.assertFalse(hasattr(candidate, "decision"))

    def test_no_cr_decision(self):
        items = [_hotlist_item()]
        candidate = build_candidate_from_cluster(items, CRClusterConfig())
        self.assertFalse(hasattr(candidate, "cr_decision"))


# ---------------------------------------------------------------------------
# build_cr_candidates integration
# ---------------------------------------------------------------------------


class TestBuildCrCandidates(unittest.TestCase):
    """Integration tests for build_cr_candidates public API."""

    def test_empty_input(self):
        result = build_cr_candidates([])
        self.assertEqual(result, [])

    def test_single_record_single_item(self):
        records = [_primitive_record(source_items=[_hotlist_item(title="Title")])]
        candidates = build_cr_candidates(records)
        self.assertEqual(len(candidates), 1)
        self.assertEqual(candidates[0].display_title, "Title")

    def test_multiple_records_merge_by_title(self):
        """Items from different primitive records merge if titles match."""
        r1 = _primitive_record(
            keyword_group="AI",
            source_items=[_hotlist_item(title="Same Title", url="https://a.com/1")],
        )
        r2 = _primitive_record(
            keyword_group="Tech",
            source_items=[_rss_item(title="Same Title", url="https://b.com/1")],
        )
        candidates = build_cr_candidates([r1, r2])
        self.assertEqual(len(candidates), 1)
        self.assertEqual(candidates[0].primary_source_type, "mixed")

    def test_multiple_records_different_titles_separate(self):
        r1 = _primitive_record(
            keyword_group="AI",
            source_items=[_hotlist_item(title="AI News", url="https://a.com/1")],
        )
        r2 = _primitive_record(
            keyword_group="Weather",
            source_items=[_hotlist_item(title="Weather Report", url="https://b.com/1")],
        )
        candidates = build_cr_candidates([r1, r2])
        self.assertEqual(len(candidates), 2)

    def test_output_sorted_by_candidate_id(self):
        """Output is sorted by candidate_id for determinism."""
        r1 = _primitive_record(source_items=[_hotlist_item(title="Zebra")])
        r2 = _primitive_record(source_items=[_hotlist_item(title="Apple")])
        candidates = build_cr_candidates([r1, r2])
        ids = [c.candidate_id for c in candidates]
        self.assertEqual(ids, sorted(ids))

    def test_custom_config(self):
        """Custom config is respected."""
        r1 = _primitive_record(source_items=[
            _hotlist_item(title="Title A", url="https://a.com/1"),
            _hotlist_item(title="Title B", url="https://b.com/1"),
        ])
        # Very strict: no merge (titles share token 'title' but sim=0.5 < 0.99).
        strict = CRClusterConfig(min_shared_tokens=100, min_similarity=0.99)
        candidates = build_cr_candidates([r1], config=strict)
        self.assertEqual(len(candidates), 2)

    def test_source_items_preserved(self):
        """Original source_items are preserved in candidate."""
        item = _hotlist_item(title="Title")
        records = [_primitive_record(source_items=[item])]
        candidates = build_cr_candidates(records)
        self.assertEqual(len(candidates[0].source_items), 1)
        self.assertIs(candidates[0].source_items[0], item)


# ---------------------------------------------------------------------------
# I. Rule 4: cross-language latin/numeric entity overlap (V3b)
# ---------------------------------------------------------------------------


# In-memory resources so tests do not depend on config/cr_entity_dictionary.yaml.
_TEST_RESOURCES = EntityResources(
    dictionary={
        "凯恩": "kane",
        "英格兰": "england",
        "克罗地亚": "croatia",
        "海力士": "hynix",
        "特朗普": "trump",
        "伊朗": "iran",
        "中国": "china",
    },
    stoplist={"england", "croatia", "trump", "iran", "china"},
)


def _entity_config(**kw) -> CRClusterConfig:
    kw.setdefault("entity_resources", _TEST_RESOURCES)
    return CRClusterConfig(**kw)


class TestExtractEntities(unittest.TestCase):
    """extract_entities: raw-title extraction of latin/numeric entities."""

    def setUp(self):
        self.d = _TEST_RESOURCES.dictionary

    def test_score_amount_percent_bignum(self):
        ents = extract_entities("Up 49% to 8300 on a $2 deal, 4-2 result", self.d)
        self.assertIn("4-2", ents)
        self.assertIn("$2", ents)
        self.assertIn("49%", ents)
        self.assertIn("8300", ents)

    def test_year_excluded(self):
        ents = extract_entities("Outlook for 2026 and 1999 recap", self.d)
        self.assertNotIn("2026", ents)
        self.assertNotIn("1999", ents)

    def test_percent_lower_bound_not_extracted(self):
        # The >= 2 floor is a non-obvious business rule; guard the boundary.
        ents = extract_entities("Up 1% and 0% growth, but 2% elsewhere", self.d)
        self.assertNotIn("1%", ents)
        self.assertNotIn("0%", ents)
        self.assertIn("2%", ents)

    def test_model_product_tokens(self):
        ents = extract_entities("GLM-5.2 vs F-35 at G7, HBM4E shipping", self.d)
        self.assertIn("glm-5.2", ents)
        self.assertIn("f-35", ents)
        self.assertIn("g7", ents)
        self.assertIn("hbm4e", ents)
        # Model token must NOT also leak its alphabetic prefix as a separate entity.
        self.assertNotIn("glm", ents)

    def test_capitalized_words(self):
        ents = extract_entities("SpaceX and Nvidia at Versailles", self.d)
        self.assertIn("spacex", ents)
        self.assertIn("nvidia", ents)
        self.assertIn("versailles", ents)

    def test_dictionary_mapping_from_chinese(self):
        ents = extract_entities("特朗普谈伊朗与中国", self.d)
        self.assertEqual(ents, {"trump", "iran", "china"})

    def test_latin_embedded_in_cjk(self):
        ents = extract_entities("SpaceX上市后股价飙升", self.d)
        self.assertIn("spacex", ents)

    def test_extraction_stopwords_filtered(self):
        ents = extract_entities("Live Updates: Breaking Video, Says New on Friday in June", self.d)
        for noise in ("live", "breaking", "video", "says", "new", "friday", "june"):
            self.assertNotIn(noise, ents)

    def test_raw_title_not_mangled(self):
        # Punctuation-bearing entities survive (would be destroyed by normalization).
        self.assertIn("1-1", extract_entities("Draw 1-1 in the final", self.d))
        self.assertIn("glm-5.2", extract_entities("GLM-5.2 released", self.d))
        self.assertIn("$2", extract_entities("A $2 trillion club", self.d))

    def test_empty_title(self):
        self.assertEqual(extract_entities("", self.d), set())


class TestIsHighSpecificity(unittest.TestCase):
    """is_high_specificity: numeric/model always; proper nouns minus stoplist."""

    def setUp(self):
        self.stop = _TEST_RESOURCES.stoplist

    def test_numeric_and_model_always_high(self):
        for e in ("4-2", "8300", "$2", "49%", "glm-5.2", "g7"):
            self.assertTrue(is_high_specificity(e, self.stop), e)

    def test_stoplisted_proper_noun_low(self):
        for e in ("england", "trump", "iran", "china"):
            self.assertFalse(is_high_specificity(e, self.stop), e)

    def test_non_stoplisted_proper_noun_high(self):
        for e in ("kane", "spacex", "hynix", "vance"):
            self.assertTrue(is_high_specificity(e, self.stop), e)


class TestRule4Merge(unittest.TestCase):
    """Rule 4 merges cross-source pairs with >= 2 shared high-specificity entities."""

    def _hl(self, title, url):
        return _hotlist_item(title=title, url=url, source_id="weibo", source_name="weibo")

    def _rss(self, title, url):
        return _rss_item(title=title, url=url, feed_id="reuters", source_name="Reuters")

    def test_merges_company_and_model(self):
        # Assert the entity set explicitly so a dictionary/extraction change
        # surfaces as a clear failure rather than a silent len(cands) == 2.
        d, stop = _TEST_RESOURCES.dictionary, _TEST_RESOURCES.stoplist
        shared = extract_entities("SK海力士HBM4E量产", d) & extract_entities(
            "SK Hynix starts HBM4E mass production", d)
        self.assertEqual(shared, {"hynix", "hbm4e"})
        self.assertEqual({e for e in shared if is_high_specificity(e, stop)}, {"hynix", "hbm4e"})

        rec = _primitive_record(source_items=[
            self._hl("SK海力士HBM4E量产", "https://hl.example.com/1"),
            self._rss("SK Hynix starts HBM4E mass production", "https://rss.example.com/1"),
        ])
        cands = build_cr_candidates([rec], config=_entity_config())
        self.assertEqual(len(cands), 1)
        self.assertEqual(cands[0].primary_source_type, "mixed")
        self.assertTrue(cands[0].has_hotlist and cands[0].has_rss)

    def test_merges_name_and_score(self):
        rec = _primitive_record(source_items=[
            self._hl("凯恩双响 英格兰4-2克罗地亚", "https://hl.example.com/2"),
            self._rss("Kane scores twice as England beat Croatia 4-2", "https://rss.example.com/2"),
        ])
        cands = build_cr_candidates([rec], config=_entity_config())
        # shared {kane, england, croatia, 4-2}; high-spec {kane, 4-2} = 2 -> merge
        self.assertEqual(len(cands), 1)
        self.assertEqual(cands[0].primary_source_type, "mixed")

    def test_no_merge_only_stoplisted_shared(self):
        rec = _primitive_record(source_items=[
            self._hl("英格兰对阵克罗地亚", "https://hl.example.com/3"),
            self._rss("England face Croatia in a friendly", "https://rss.example.com/3"),
        ])
        cands = build_cr_candidates([rec], config=_entity_config())
        # shared {england, croatia} but 0 high-spec -> no merge
        self.assertEqual(len(cands), 2)

    def test_no_merge_generic_trump_iran(self):
        rec = _primitive_record(source_items=[
            self._hl("特朗普谈伊朗", "https://hl.example.com/4"),
            self._rss("Trump comments on Iran tensions", "https://rss.example.com/4"),
        ])
        cands = build_cr_candidates([rec], config=_entity_config())
        # shared {trump, iran} both stoplisted -> 0 high-spec -> no merge (report FP killed)
        self.assertEqual(len(cands), 2)

    def test_below_threshold_no_merge(self):
        rec = _primitive_record(source_items=[
            self._hl("海力士发布会", "https://hl.example.com/5"),
            self._rss("SK Hynix annual event", "https://rss.example.com/5"),
        ])
        cands = build_cr_candidates([rec], config=_entity_config())
        # only {hynix} shared = 1 < 2 -> no merge
        self.assertEqual(len(cands), 2)


class TestRule4Gating(unittest.TestCase):
    """Rule 4 only fires across source types; characterizes transitive bridging."""

    def test_same_source_type_not_merged_by_rule4(self):
        # Disable Rule 3 (min_shared_tokens huge) to isolate Rule 4 behaviour.
        cfg = _entity_config(min_shared_tokens=100, min_similarity=0.99)
        rec = _primitive_record(source_items=[
            _hotlist_item(title="SpaceX 8300 点评", url="https://a.com/1", source_id="weibo"),
            _hotlist_item(title="8300 SpaceX 分析", url="https://b.com/1", source_id="douyin"),
        ])
        cands = build_cr_candidates([rec], config=cfg)
        # Both hotlist; share {spacex, 8300} but Rule 4 is gated to hotlist+rss -> no merge.
        self.assertEqual(len(cands), 2)

    def test_cross_source_same_entities_merges(self):
        # Same entities, but now one side is RSS -> Rule 4 applies.
        cfg = _entity_config(min_shared_tokens=100, min_similarity=0.99)
        rec = _primitive_record(source_items=[
            _hotlist_item(title="SpaceX 8300 点评", url="https://a.com/1", source_id="weibo"),
            _rss_item(title="8300 SpaceX analysis", url="https://b.com/1", feed_id="reuters"),
        ])
        cands = build_cr_candidates([rec], config=cfg)
        self.assertEqual(len(cands), 1)

    def test_transitive_bridging_prevented(self):
        # A "roundup" RSS X matches BOTH hotlist A and hotlist B by entities.
        # Single-best-attach must NOT bridge A and B into one mega-cluster:
        # X joins exactly one hotlist cluster, the other stays distinct.
        cfg = _entity_config(min_shared_tokens=100, min_similarity=0.99)
        a = _hotlist_item(title="SpaceX 8300 点评", url="https://a.com/1", source_id="weibo")
        b = _hotlist_item(title="8300 SpaceX 大涨", url="https://b.com/1", source_id="douyin")
        x = _rss_item(title="SpaceX hits 8300 milestone", url="https://x.com/1", feed_id="reuters")
        cands = build_cr_candidates([_primitive_record(source_items=[a, x, b])], config=cfg)
        # A and B are NOT bridged: two distinct candidates.
        self.assertEqual(len(cands), 2)
        # X attached to exactly one of them → cluster sizes are {2, 1}.
        self.assertEqual(sorted(len(c.source_items) for c in cands), [1, 2])

    def test_roundup_rss_distinct_events_not_bridged(self):
        # Roundup RSS shares a DIFFERENT high-spec pair with each of two
        # genuinely distinct events; must attach to one, never bridge them.
        cfg = _entity_config(min_shared_tokens=100, min_similarity=0.99)
        a = _hotlist_item(title="SpaceX 8300 点评", url="https://a.com/1", source_id="weibo")
        b = _hotlist_item(title="SK海力士HBM4E量产", url="https://b.com/1", source_id="douyin")
        x = _rss_item(title="Markets recap: SpaceX 8300 and SK Hynix HBM4E",
                      url="https://x.com/1", feed_id="reuters")
        cands = build_cr_candidates([_primitive_record(source_items=[a, x, b])], config=cfg)
        self.assertEqual(len(cands), 2)
        self.assertEqual(sorted(len(c.source_items) for c in cands), [1, 2])


class TestCanonicalClusterKey(unittest.TestCase):
    """hotlist-first cluster_key: stable under RSS churn, legacy-identical when off."""

    def _mixed(self, rss_title, rss_url):
        return _primitive_record(source_items=[
            _hotlist_item(title="SK海力士HBM4E量产", url="https://hl.example.com/k",
                          source_id="weibo"),
            _rss_item(title=rss_title, url=rss_url, feed_id="reuters"),
        ])

    def test_key_stable_across_rss_churn(self):
        a = build_cr_candidates([self._mixed("SK Hynix HBM4E mass production starts",
                                             "https://rss.example.com/a")], config=_entity_config())
        b = build_cr_candidates([self._mixed("SK Hynix HBM4E shipments to Nvidia begin",
                                             "https://rss.example.com/b")], config=_entity_config())
        self.assertEqual(len(a), 1)
        self.assertEqual(len(b), 1)
        # Different RSS item each run, same hotlist core -> identical key.
        self.assertEqual(a[0].cluster_key, b[0].cluster_key)
        self.assertEqual(a[0].candidate_id, b[0].candidate_id)

    def test_hotlist_only_key_identical_on_off(self):
        rec = _primitive_record(source_items=[_hotlist_item(title="纯热榜事件", url="https://h.com/1")])
        on = build_cr_candidates([rec], config=_entity_config(use_entity_match=True))
        off = build_cr_candidates([rec], config=_entity_config(use_entity_match=False))
        self.assertEqual(on[0].cluster_key, off[0].cluster_key)

    def test_rss_only_key_identical_on_off(self):
        rec = _primitive_record(source_items=[_rss_item(title="RSS only event", url="https://r.com/1")])
        on = build_cr_candidates([rec], config=_entity_config(use_entity_match=True))
        off = build_cr_candidates([rec], config=_entity_config(use_entity_match=False))
        self.assertEqual(on[0].cluster_key, off[0].cluster_key)


class TestUseEntityMatchOff(unittest.TestCase):
    """use_entity_match=False fully restores legacy behaviour."""

    def test_no_rule4_merge_when_off(self):
        rec = _primitive_record(source_items=[
            _hotlist_item(title="SK海力士HBM4E量产", url="https://hl.example.com/1", source_id="weibo"),
            _rss_item(title="SK Hynix starts HBM4E mass production", url="https://rss.example.com/1",
                      feed_id="reuters"),
        ])
        cands = build_cr_candidates([rec], config=_entity_config(use_entity_match=False))
        self.assertEqual(len(cands), 2)


class TestRule4ScoringActivation(unittest.TestCase):
    """A merged mixed candidate auto-activates the (previously dormant) cross-evidence path."""

    def test_mixed_candidate_activates_cooccurrence_and_strong(self):
        rec = _primitive_record(source_items=[
            _hotlist_item(title="SK海力士HBM4E量产", url="https://hl.example.com/1",
                          source_id="weibo", current_rank=3, normalized_rank=3),
            _rss_item(title="SK Hynix starts HBM4E mass production", url="https://rss.example.com/1",
                      feed_id="reuters"),
        ])
        cands = build_cr_candidates([rec], config=_entity_config())
        self.assertEqual(len(cands), 1)
        cand = cands[0]
        self.assertEqual(cand.primary_source_type, "mixed")

        cl = score_cross_layer_raw(cand)
        self.assertIn("hotlist_rss_cooccurrence=7", cl.reasons)

        result = score_cr_candidate(cand)
        em = result.debug["evidence_multiplier"]
        self.assertEqual(em["reason"], "strong_cross_evidence")
        self.assertAlmostEqual(em["multiplier"], 1.10)


class TestEntityResourceLoader(unittest.TestCase):
    """Loader degrades gracefully on missing / malformed / null files."""

    def setUp(self):
        clear_entity_resources_cache()
        self.addCleanup(clear_entity_resources_cache)

    def test_missing_file_returns_empty(self):
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            res = load_entity_resources(config_dir=d)
            self.assertEqual(res.dictionary, {})
            self.assertEqual(res.stoplist, set())

    @unittest.skipUnless(_HAS_YAML, "PyYAML required to exercise the parse path")
    def test_malformed_yaml_returns_empty(self):
        import os
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            with open(os.path.join(d, "cr_entity_dictionary.yaml"), "w", encoding="utf-8") as f:
                f.write("::: not : valid : yaml :::\n  - [unclosed\n")
            res = load_entity_resources(config_dir=d)
            self.assertEqual(res.dictionary, {})

    @unittest.skipUnless(_HAS_YAML, "PyYAML required to exercise the parse path")
    def test_null_fields_no_crash(self):
        import os
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            with open(os.path.join(d, "cr_entity_dictionary.yaml"), "w", encoding="utf-8") as f:
                f.write("dictionary: null\nstoplist: null\n")
            res = load_entity_resources(config_dir=d)
            self.assertEqual(res.dictionary, {})
            self.assertEqual(res.stoplist, set())

    @unittest.skipUnless(_HAS_YAML, "PyYAML required to exercise the parse path")
    def test_list_value_skipped_in_v1(self):
        import os
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            with open(os.path.join(d, "cr_entity_dictionary.yaml"), "w", encoding="utf-8") as f:
                f.write("dictionary:\n  特朗普: trump\n  欧盟: [eu, european union]\nstoplist:\n  - trump\n")
            res = load_entity_resources(config_dir=d)
            self.assertEqual(res.dictionary, {"特朗普": "trump"})  # list value skipped
            self.assertEqual(res.stoplist, {"trump"})


if __name__ == "__main__":
    unittest.main()
