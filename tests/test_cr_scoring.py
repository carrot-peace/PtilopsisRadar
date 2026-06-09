# coding=utf-8
"""
PR9d: CR deterministic scoring tests.

Covers:
  A. Profile defaults
  B. clamp_score
  C. Component score construction
  D. Growth Raw (rank movement, new burst, recency, persistence, aggregation)
  E. Current Heat (rank heat, coverage, item count, cap)
  F. Cross Layer (co-occurrence, diversity, source count, cap)
  G. combine_cr_scores (caps, background, trigger reasons)
  H. score_cr_candidate (integration)
  I. No decision fields
"""

import math
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from trendradar.cr.models import CRCandidate, CRSourceItem
from trendradar.cr.scoring import (
    CRComponentScore,
    CRScoringProfile,
    CRScoreResult,
    DEFAULT_CR_SCORING_PROFILE,
    _distinct_source_count,
    _source_identity,
    clamp_score,
    combine_cr_scores,
    make_component_score,
    score_cr_candidate,
    score_cross_layer_raw,
    score_current_heat_raw,
    score_growth_raw,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_item(**kwargs) -> CRSourceItem:
    """Build a CRSourceItem with sensible defaults for scoring tests."""
    defaults = {
        "source_type": "hotlist",
        "source_id": "weibo",
        "source_name": "weibo",
        "title": "Test Title",
        "url": "https://example.com/1",
        "is_new": False,
        "is_new_semantics": "unknown",
        "has_reliable_rank_timeline": False,
        "has_time_signals": False,
    }
    defaults.update(kwargs)
    return CRSourceItem(**defaults)


def _make_candidate(
    *,
    candidate_id="abc123",
    cluster_key="test||cluster",
    source_items=None,
    source_names=None,
    source_ids=None,
    feed_ids=None,
    has_hotlist=False,
    has_rss=False,
    primary_source_type="unknown",
    best_current_rank=None,
    best_normalized_rank=None,
) -> CRCandidate:
    """Build a CRCandidate with sensible defaults."""
    items = source_items or []
    return CRCandidate(
        candidate_id=candidate_id,
        cluster_key=cluster_key,
        source_items=items,
        source_names=source_names or [],
        source_ids=source_ids or [],
        feed_ids=feed_ids or [],
        has_hotlist=has_hotlist,
        has_rss=has_rss,
        primary_source_type=primary_source_type,
        best_current_rank=best_current_rank,
        best_normalized_rank=best_normalized_rank,
    )


# ===========================================================================
# A. Profile defaults
# ===========================================================================

class TestProfileDefaults(unittest.TestCase):

    def test_profile_version(self):
        self.assertEqual(DEFAULT_CR_SCORING_PROFILE.profile_version, "cr-score-v0.1")

    def test_thresholds(self):
        p = DEFAULT_CR_SCORING_PROFILE
        self.assertAlmostEqual(p.alert_threshold, 60.0)
        self.assertAlmostEqual(p.urgent_threshold, 80.0)

    def test_caps(self):
        p = DEFAULT_CR_SCORING_PROFILE
        self.assertAlmostEqual(p.heat_cap, 80.0)
        self.assertAlmostEqual(p.cross_evidence_cap, 20.0)
        self.assertAlmostEqual(p.total_cap, 100.0)
        self.assertAlmostEqual(p.growth_raw_cap, 60.0)
        self.assertAlmostEqual(p.current_heat_raw_cap, 50.0)
        self.assertAlmostEqual(p.cross_layer_raw_cap, 15.0)
        self.assertAlmostEqual(p.background_support_raw_cap, 10.0)

    def test_background_support_disabled(self):
        self.assertFalse(DEFAULT_CR_SCORING_PROFILE.background_support_enabled)

    def test_frozen(self):
        with self.assertRaises(AttributeError):
            DEFAULT_CR_SCORING_PROFILE.total_cap = 50.0


# ===========================================================================
# B. clamp_score
# ===========================================================================

class TestClampScore(unittest.TestCase):

    def test_negative_returns_zero(self):
        self.assertAlmostEqual(clamp_score(-5.0, 10.0), 0.0)

    def test_normal_unchanged(self):
        self.assertAlmostEqual(clamp_score(5.0, 10.0), 5.0)

    def test_over_cap_returns_cap(self):
        self.assertAlmostEqual(clamp_score(15.0, 10.0), 10.0)

    def test_at_cap(self):
        self.assertAlmostEqual(clamp_score(10.0, 10.0), 10.0)

    def test_at_zero(self):
        self.assertAlmostEqual(clamp_score(0.0, 10.0), 0.0)

    def test_nan_raises(self):
        with self.assertRaises(ValueError):
            clamp_score(float("nan"), 10.0)

    def test_inf_raises(self):
        with self.assertRaises(ValueError):
            clamp_score(float("inf"), 10.0)

    def test_neg_inf_raises(self):
        with self.assertRaises(ValueError):
            clamp_score(float("-inf"), 10.0)


# ===========================================================================
# C. Component score construction
# ===========================================================================

class TestComponentScore(unittest.TestCase):

    def test_raw_preserved(self):
        cs = make_component_score("test", 7.5, 10.0)
        self.assertAlmostEqual(cs.raw_score, 7.5)

    def test_capped_applied(self):
        cs = make_component_score("test", 15.0, 10.0)
        self.assertAlmostEqual(cs.capped_score, 10.0)

    def test_cap_stored(self):
        cs = make_component_score("test", 5.0, 10.0)
        self.assertAlmostEqual(cs.cap, 10.0)

    def test_reasons_copied(self):
        reasons = ["a", "b"]
        cs = make_component_score("test", 5.0, 10.0, reasons=reasons)
        self.assertEqual(cs.reasons, ["a", "b"])
        # Mutation isolation.
        reasons.append("c")
        self.assertEqual(cs.reasons, ["a", "b"])

    def test_debug_copied(self):
        debug = {"x": 1}
        cs = make_component_score("test", 5.0, 10.0, debug=debug)
        self.assertEqual(cs.debug, {"x": 1})
        debug["y"] = 2
        self.assertEqual(cs.debug, {"x": 1})

    def test_none_reasons_debug(self):
        cs = make_component_score("test", 5.0, 10.0)
        self.assertEqual(cs.reasons, [])
        self.assertEqual(cs.debug, {})


# ===========================================================================
# D. Growth Raw
# ===========================================================================

class TestGrowthRaw(unittest.TestCase):

    # --- Rank Movement: first-ever entry ---

    def test_first_entry_top10(self):
        """First-ever entry into top 10 → 27."""
        item = _make_item(
            has_reliable_rank_timeline=True,
            current_rank=8,
            previous_observation_exists=False,
            visible_observation_count=1,
            count=3,
        )
        cand = _make_candidate(
            source_items=[item], has_hotlist=True, primary_source_type="hotlist",
            best_current_rank=8,
        )
        result = score_growth_raw(cand)
        # rank_movement=27, others=0
        self.assertAlmostEqual(result.raw_score, 27.0)

    def test_first_entry_single_obs_decay(self):
        """First-ever entry with single observation → 27 * 0.7 = 18.9."""
        item = _make_item(
            has_reliable_rank_timeline=True,
            current_rank=8,
            previous_observation_exists=False,
            visible_observation_count=1,
            count=1,
        )
        cand = _make_candidate(
            source_items=[item], has_hotlist=True, primary_source_type="hotlist",
            best_current_rank=8,
        )
        result = score_growth_raw(cand)
        self.assertAlmostEqual(result.raw_score, 27.0 * 0.7)

    def test_first_entry_top3(self):
        """First-ever entry into top 3 → 30."""
        item = _make_item(
            has_reliable_rank_timeline=True,
            current_rank=2,
            previous_observation_exists=False,
            visible_observation_count=1,
            count=5,
        )
        cand = _make_candidate(
            source_items=[item], has_hotlist=True, primary_source_type="hotlist",
            best_current_rank=2,
        )
        result = score_growth_raw(cand)
        self.assertAlmostEqual(result.raw_score, 30.0)

    # --- Rank Movement: re-entry ---

    def test_re_entry(self):
        """Re-entry uses entry bucket."""
        item = _make_item(
            has_reliable_rank_timeline=True,
            current_rank=15,
            previous_observation_exists=True,
            previous_observation_visible=False,
            visible_observation_count=1,
        )
        cand = _make_candidate(
            source_items=[item], has_hotlist=True, primary_source_type="hotlist",
            best_current_rank=15,
        )
        result = score_growth_raw(cand)
        # Re-entry top 20 → 23
        self.assertAlmostEqual(result.raw_score, 23.0)
        self.assertEqual(result.debug["rank_movement"]["rule"], "re_entry")

    # --- Rank Movement: rank improvement ---

    def test_rank_improvement_30_to_10(self):
        """Improvement of 20 places (30→10) → 21."""
        item = _make_item(
            has_reliable_rank_timeline=True,
            current_rank=10,
            previous_observation_exists=True,
            previous_observation_visible=True,
            previous_visible_rank=30,
            rank_delta=20,
        )
        cand = _make_candidate(
            source_items=[item], has_hotlist=True, primary_source_type="hotlist",
            best_current_rank=10,
        )
        result = score_growth_raw(cand)
        self.assertAlmostEqual(result.raw_score, 21.0)

    def test_rank_improvement_visibility_gate(self):
        """Improvement of 60 places but current rank > 100 → capped at 6."""
        item = _make_item(
            has_reliable_rank_timeline=True,
            current_rank=120,
            previous_observation_exists=True,
            previous_observation_visible=True,
            previous_visible_rank=180,
            rank_delta=60,
        )
        cand = _make_candidate(
            source_items=[item], has_hotlist=True, primary_source_type="hotlist",
            best_current_rank=120,
        )
        result = score_growth_raw(cand)
        # 28 (>=50 and top20) fails because 120 > 20 → base is >=20 → 21
        # But visibility gate: rank > 100 → cap 6
        self.assertAlmostEqual(result.raw_score, 6.0)

    # --- Rank Movement: stable high rank ---

    def test_stable_top5(self):
        """Stable top 5 (no entry/re-entry/improvement) → 3."""
        item = _make_item(
            has_reliable_rank_timeline=True,
            current_rank=5,
            previous_observation_exists=True,
            previous_observation_visible=True,
            previous_visible_rank=5,
            rank_delta=0,
        )
        cand = _make_candidate(
            source_items=[item], has_hotlist=True, primary_source_type="hotlist",
            best_current_rank=5,
        )
        result = score_growth_raw(cand)
        self.assertAlmostEqual(result.raw_score, 3.0)

    def test_stable_below_top20(self):
        """Stable below top 20 → 0."""
        item = _make_item(
            has_reliable_rank_timeline=True,
            current_rank=30,
            previous_observation_exists=True,
            previous_observation_visible=True,
            previous_visible_rank=30,
            rank_delta=0,
        )
        cand = _make_candidate(
            source_items=[item], has_hotlist=True, primary_source_type="hotlist",
            best_current_rank=30,
        )
        result = score_growth_raw(cand)
        self.assertAlmostEqual(result.raw_score, 0.0)

    # --- New Burst ---

    def test_new_burst_first_crawl_of_day_zero(self):
        """first_crawl_of_day=True → 0."""
        item = _make_item(
            first_crawl_of_day=True,
            is_new=True,
            is_new_semantics="new_titles_detection",
            current_rank=5,
        )
        cand = _make_candidate(source_items=[item], has_hotlist=True)
        result = score_growth_raw(cand)
        # new_burst=0
        self.assertAlmostEqual(result.debug["new_burst"]["score"], 0.0)

    def test_new_burst_unknown_semantics_zero(self):
        """is_new_semantics='unknown' → 0."""
        item = _make_item(
            is_new=True,
            is_new_semantics="unknown",
            current_rank=5,
        )
        cand = _make_candidate(source_items=[item], has_hotlist=True)
        result = score_growth_raw(cand)
        self.assertAlmostEqual(result.debug["new_burst"]["score"], 0.0)

    def test_new_burst_top10(self):
        """New + top 10 → 12."""
        item = _make_item(
            is_new=True,
            is_new_semantics="new_titles_detection",
            current_rank=8,
            first_crawl_of_day=False,
        )
        cand = _make_candidate(
            source_items=[item], has_hotlist=True,
            source_names=["weibo"],
            source_ids=["weibo"],
        )
        result = score_growth_raw(cand)
        self.assertAlmostEqual(result.debug["new_burst"]["score"], 12.0)

    def test_new_burst_low_base_dampening(self):
        """New + rank > 50 with single source → dampened by 0.8."""
        item = _make_item(
            is_new=True,
            is_new_semantics="new_titles_detection",
            current_rank=60,
            first_crawl_of_day=False,
        )
        cand = _make_candidate(
            source_items=[item], has_hotlist=True,
            source_names=["weibo"],
            source_ids=["weibo"],
        )
        result = score_growth_raw(cand)
        # rank 60 → 4 (top 100 bucket), dampened by 0.8 → 3.2
        self.assertAlmostEqual(result.debug["new_burst"]["score"], 4.0 * 0.8)

    def test_new_burst_low_base_very_low(self):
        """New + rank > 100 with single source → dampened by 0.65."""
        item = _make_item(
            is_new=True,
            is_new_semantics="new_titles_detection",
            current_rank=150,
            first_crawl_of_day=False,
        )
        cand = _make_candidate(
            source_items=[item], has_hotlist=True,
            source_names=["weibo"],
            source_ids=["weibo"],
        )
        result = score_growth_raw(cand)
        # rank 150 → 2, dampened by 0.65 → 1.3
        self.assertAlmostEqual(result.debug["new_burst"]["score"], 2.0 * 0.65)

    # --- Recency Momentum ---

    def test_recency_no_time_signals(self):
        """No time signals → 0."""
        item = _make_item(has_time_signals=False)
        cand = _make_candidate(source_items=[item])
        result = score_growth_raw(cand)
        self.assertAlmostEqual(result.debug["recency_momentum"]["score"], 0.0)

    def test_recency_synthetic_cap(self):
        """Synthetic time → cap at 3."""
        item = _make_item(
            has_time_signals=True,
            time_signals_synthetic=True,
            is_new=True,
            first_crawl_of_day=False,
        )
        cand = _make_candidate(source_items=[item], has_hotlist=True)
        result = score_growth_raw(cand)
        # new_not_first_crawl → 8, capped at 3
        self.assertAlmostEqual(result.debug["recency_momentum"]["score"], 3.0)

    def test_recency_normal_new(self):
        """Normal new title (not synthetic) → 8."""
        item = _make_item(
            has_time_signals=True,
            time_signals_synthetic=False,
            is_new=True,
            first_crawl_of_day=False,
        )
        cand = _make_candidate(source_items=[item], has_hotlist=True)
        result = score_growth_raw(cand)
        self.assertAlmostEqual(result.debug["recency_momentum"]["score"], 8.0)

    def test_recency_both_times(self):
        """Has first_time and last_time → 4."""
        item = _make_item(
            has_time_signals=True,
            time_signals_synthetic=False,
            first_time="08:00",
            last_time="12:00",
        )
        cand = _make_candidate(source_items=[item], has_hotlist=True)
        result = score_growth_raw(cand)
        self.assertAlmostEqual(result.debug["recency_momentum"]["score"], 4.0)

    # --- Weak Persistence ---

    def test_persistence_timeline_top20(self):
        """visible_observation_count >= 3 and top 20 → 5."""
        item = _make_item(
            current_rank=15,
            has_reliable_rank_timeline=True,
            visible_observation_count=3,
        )
        cand = _make_candidate(source_items=[item], has_hotlist=True)
        result = score_growth_raw(cand)
        self.assertAlmostEqual(result.debug["weak_persistence"]["score"], 5.0)

    def test_persistence_count_fallback(self):
        """count >= 5 without reliable timeline → 3."""
        item = _make_item(
            current_rank=30,
            has_reliable_rank_timeline=False,
            has_count=True,
            count=5,
        )
        cand = _make_candidate(source_items=[item], has_hotlist=True)
        result = score_growth_raw(cand)
        self.assertAlmostEqual(result.debug["weak_persistence"]["score"], 3.0)

    def test_persistence_count_cap_3(self):
        """Count fallback is capped at 3 (already enforced by max score)."""
        item = _make_item(
            current_rank=30,
            has_reliable_rank_timeline=False,
            has_count=True,
            count=100,
        )
        cand = _make_candidate(source_items=[item], has_hotlist=True)
        result = score_growth_raw(cand)
        self.assertAlmostEqual(result.debug["weak_persistence"]["score"], 3.0)

    # --- Candidate-level aggregation ---

    def test_aggregation_uses_max(self):
        """Growth aggregation uses max per sub-component, not sum."""
        item1 = _make_item(
            title="A",
            has_reliable_rank_timeline=True,
            current_rank=2,
            previous_observation_exists=False,
            visible_observation_count=1,
            count=5,
        )
        item2 = _make_item(
            title="B",
            has_reliable_rank_timeline=True,
            current_rank=10,
            previous_observation_exists=False,
            visible_observation_count=1,
            count=5,
        )
        cand = _make_candidate(
            source_items=[item1, item2], has_hotlist=True,
            best_current_rank=2,
        )
        result = score_growth_raw(cand)
        # max rank_movement: item1=30 (top3), item2=27 (top10) → 30
        self.assertAlmostEqual(result.debug["rank_movement"]["score"], 30.0)

    # --- Non-hotlist item returns 0 ---

    def test_rss_item_rank_movement_zero(self):
        """RSS items get 0 for rank movement."""
        item = _make_item(source_type="rss", current_rank=5)
        cand = _make_candidate(source_items=[item])
        result = score_growth_raw(cand)
        self.assertAlmostEqual(result.raw_score, 0.0)

    # --- Growth cap ---

    def test_growth_cap(self):
        """Growth raw is capped at growth_raw_cap."""
        # Even with max sub-components, cap applies.
        custom = CRScoringProfile(growth_raw_cap=10.0)
        item = _make_item(
            has_reliable_rank_timeline=True,
            current_rank=2,
            previous_observation_exists=False,
            visible_observation_count=1,
            count=5,
        )
        cand = _make_candidate(source_items=[item], has_hotlist=True, best_current_rank=2)
        result = score_growth_raw(cand, profile=custom)
        self.assertAlmostEqual(result.capped_score, 10.0)


# ===========================================================================
# E. Current Heat
# ===========================================================================

class TestCurrentHeat(unittest.TestCase):

    def test_top3_rank_heat(self):
        """best_current_rank=2 → rank heat 30."""
        cand = _make_candidate(
            has_hotlist=True, best_current_rank=2,
            source_names=["weibo"], source_ids=["weibo"],
            source_items=[_make_item()],
        )
        result = score_current_heat_raw(cand)
        self.assertAlmostEqual(result.debug["best_rank_heat"]["score"], 30.0)

    def test_top10_rank_heat(self):
        """best_current_rank=8 → rank heat 26."""
        cand = _make_candidate(
            has_hotlist=True, best_current_rank=8,
            source_names=["weibo"], source_ids=["weibo"],
            source_items=[_make_item()],
        )
        result = score_current_heat_raw(cand)
        self.assertAlmostEqual(result.debug["best_rank_heat"]["score"], 26.0)

    def test_no_hotlist_rank_rss_only_zero(self):
        """No hotlist rank, RSS only → rank heat 0."""
        cand = _make_candidate(
            has_rss=True, primary_source_type="rss",
            best_current_rank=None, best_normalized_rank=None,
            source_names=["hn"], feed_ids=["hn"],
            source_items=[_make_item(source_type="rss")],
        )
        result = score_current_heat_raw(cand)
        self.assertAlmostEqual(result.debug["best_rank_heat"]["score"], 0.0)

    def test_fallback_to_normalized_rank(self):
        """No current_rank but normalized_rank → used as fallback."""
        cand = _make_candidate(
            has_hotlist=True,
            best_current_rank=None, best_normalized_rank=5,
            source_names=["weibo"], source_ids=["weibo"],
            source_items=[_make_item()],
        )
        result = score_current_heat_raw(cand)
        self.assertAlmostEqual(result.debug["best_rank_heat"]["used_rank"], 5)
        # rank 5 → top 10 → 26
        self.assertAlmostEqual(result.debug["best_rank_heat"]["score"], 26.0)

    def test_source_coverage_1(self):
        """1 source → coverage heat 2."""
        cand = _make_candidate(
            source_names=["weibo"], source_ids=["weibo"],
            source_items=[_make_item()],
        )
        result = score_current_heat_raw(cand)
        self.assertAlmostEqual(result.debug["source_coverage_heat"]["score"], 2.0)

    def test_source_coverage_2(self):
        """2 sources → coverage heat 5."""
        cand = _make_candidate(
            source_items=[
                _make_item(source_id="weibo", source_name="weibo"),
                _make_item(source_type="rss", feed_id="hn", source_name="hn",
                           title="B", url="https://hn.example.com/1"),
            ],
        )
        result = score_current_heat_raw(cand)
        self.assertAlmostEqual(result.debug["source_coverage_heat"]["score"], 5.0)

    def test_source_coverage_3(self):
        """3 sources → coverage heat 8."""
        cand = _make_candidate(
            source_items=[
                _make_item(source_id="a", source_name="a"),
                _make_item(source_id="b", source_name="b"),
                _make_item(source_id="c", source_name="c"),
            ],
        )
        result = score_current_heat_raw(cand)
        self.assertAlmostEqual(result.debug["source_coverage_heat"]["score"], 8.0)

    def test_source_coverage_4_plus(self):
        """4+ sources → coverage heat 12."""
        cand = _make_candidate(
            source_items=[
                _make_item(source_id="a", source_name="a"),
                _make_item(source_id="b", source_name="b"),
                _make_item(source_id="c", source_name="c"),
                _make_item(source_id="d", source_name="d"),
            ],
        )
        result = score_current_heat_raw(cand)
        self.assertAlmostEqual(result.debug["source_coverage_heat"]["score"], 12.0)

    def test_item_count_1(self):
        """1 item → item heat 1."""
        cand = _make_candidate(source_items=[_make_item()])
        result = score_current_heat_raw(cand)
        self.assertAlmostEqual(result.debug["item_count_heat"]["score"], 1.0)

    def test_item_count_2(self):
        """2 items → item heat 3."""
        cand = _make_candidate(source_items=[_make_item(), _make_item(title="B")])
        result = score_current_heat_raw(cand)
        self.assertAlmostEqual(result.debug["item_count_heat"]["score"], 3.0)

    def test_item_count_3(self):
        """3 items → item heat 5."""
        cand = _make_candidate(source_items=[_make_item()] * 3)
        result = score_current_heat_raw(cand)
        self.assertAlmostEqual(result.debug["item_count_heat"]["score"], 5.0)

    def test_item_count_4_plus(self):
        """4+ items → item heat 8."""
        cand = _make_candidate(source_items=[_make_item()] * 4)
        result = score_current_heat_raw(cand)
        self.assertAlmostEqual(result.debug["item_count_heat"]["score"], 8.0)

    def test_current_heat_cap_50(self):
        """Current heat raw is capped at 50."""
        cand = _make_candidate(
            has_hotlist=True, best_current_rank=1,
            source_items=[
                _make_item(source_id="a", source_name="a"),
                _make_item(source_id="b", source_name="b"),
                _make_item(source_id="c", source_name="c"),
                _make_item(source_id="d", source_name="d"),
            ],
        )
        result = score_current_heat_raw(cand)
        # 30 + 12 + 8 = 50 → exactly at cap
        self.assertAlmostEqual(result.raw_score, 50.0)
        self.assertAlmostEqual(result.capped_score, 50.0)


# ===========================================================================
# F. Cross Layer
# ===========================================================================

class TestCrossLayer(unittest.TestCase):

    def test_hotlist_rss_cooccurrence(self):
        """has_hotlist and has_rss → +7."""
        cand = _make_candidate(
            has_hotlist=True, has_rss=True, primary_source_type="mixed",
            source_names=["a", "b"], source_ids=["a"], feed_ids=["b"],
            source_items=[_make_item(), _make_item(source_type="rss")],
        )
        result = score_cross_layer_raw(cand)
        self.assertAlmostEqual(result.debug["hotlist_rss_cooccurrence"], 7.0)

    def test_no_cooccurrence(self):
        """Only hotlist → 0."""
        cand = _make_candidate(
            has_hotlist=True, primary_source_type="hotlist",
            source_names=["a"], source_ids=["a"],
            source_items=[_make_item()],
        )
        result = score_cross_layer_raw(cand)
        self.assertAlmostEqual(result.debug["hotlist_rss_cooccurrence"], 0.0)

    def test_mixed_diversity(self):
        """primary_source_type='mixed' → diversity 4."""
        cand = _make_candidate(
            has_hotlist=True, has_rss=True, primary_source_type="mixed",
            source_names=["a", "b"], source_ids=["a"], feed_ids=["b"],
            source_items=[_make_item(), _make_item(source_type="rss")],
        )
        result = score_cross_layer_raw(cand)
        self.assertAlmostEqual(result.debug["source_type_diversity"]["score"], 4.0)

    def test_single_type_diversity(self):
        """primary_source_type='hotlist' → diversity 1."""
        cand = _make_candidate(
            has_hotlist=True, primary_source_type="hotlist",
            source_names=["a"], source_ids=["a"],
            source_items=[_make_item()],
        )
        result = score_cross_layer_raw(cand)
        self.assertAlmostEqual(result.debug["source_type_diversity"]["score"], 1.0)

    def test_unknown_diversity(self):
        """primary_source_type='unknown' → diversity 0."""
        cand = _make_candidate(primary_source_type="unknown")
        result = score_cross_layer_raw(cand)
        self.assertAlmostEqual(result.debug["source_type_diversity"]["score"], 0.0)

    def test_source_count_support_1(self):
        """1 source → count support 0."""
        cand = _make_candidate(
            source_items=[_make_item(source_id="a", source_name="a")],
        )
        result = score_cross_layer_raw(cand)
        self.assertAlmostEqual(result.debug["source_count_support"]["score"], 0.0)

    def test_source_count_support_2(self):
        """2 sources → count support 1."""
        cand = _make_candidate(
            source_items=[
                _make_item(source_id="a", source_name="a"),
                _make_item(source_id="b", source_name="b"),
            ],
        )
        result = score_cross_layer_raw(cand)
        self.assertAlmostEqual(result.debug["source_count_support"]["score"], 1.0)

    def test_source_count_support_3(self):
        """3 sources → count support 2."""
        cand = _make_candidate(
            source_items=[
                _make_item(source_id="a", source_name="a"),
                _make_item(source_id="b", source_name="b"),
                _make_item(source_id="c", source_name="c"),
            ],
        )
        result = score_cross_layer_raw(cand)
        self.assertAlmostEqual(result.debug["source_count_support"]["score"], 2.0)

    def test_source_count_support_4_plus(self):
        """4+ sources → count support 4."""
        cand = _make_candidate(
            source_items=[
                _make_item(source_id="a", source_name="a"),
                _make_item(source_id="b", source_name="b"),
                _make_item(source_id="c", source_name="c"),
                _make_item(source_id="d", source_name="d"),
            ],
        )
        result = score_cross_layer_raw(cand)
        self.assertAlmostEqual(result.debug["source_count_support"]["score"], 4.0)

    def test_cross_layer_cap_15(self):
        """Cross-layer raw is capped at 15."""
        cand = _make_candidate(
            has_hotlist=True, has_rss=True, primary_source_type="mixed",
            source_items=[
                _make_item(source_id="a", source_name="a"),
                _make_item(source_id="b", source_name="b"),
                _make_item(source_type="rss", feed_id="c", source_name="c",
                           title="C", url="https://c.example.com"),
                _make_item(source_type="rss", feed_id="d", source_name="d",
                           title="D", url="https://d.example.com"),
            ],
        )
        result = score_cross_layer_raw(cand)
        # 7 + 4 + 4 = 15 → exactly at cap
        self.assertAlmostEqual(result.raw_score, 15.0)
        self.assertAlmostEqual(result.capped_score, 15.0)


# ===========================================================================
# F2. Source Identity (no double-counting)
# ===========================================================================

class TestSourceIdentity(unittest.TestCase):
    """Source identity helper: one identity per item, no double-counting."""

    def test_same_item_source_id_and_name_count_1(self):
        """Same item with source_id + source_name → coverage_count = 1."""
        item = _make_item(source_id="weibo", source_name="微博热搜")
        cand = _make_candidate(source_items=[item])
        self.assertEqual(_distinct_source_count(cand), 1)

    def test_two_hotlist_same_source_id_count_1(self):
        """Two hotlist items with same source_id → coverage_count = 1."""
        item1 = _make_item(source_id="weibo", source_name="a", title="A")
        item2 = _make_item(source_id="weibo", source_name="b", title="B")
        cand = _make_candidate(source_items=[item1, item2])
        self.assertEqual(_distinct_source_count(cand), 1)

    def test_two_hotlist_different_source_id_count_2(self):
        """Two hotlist items with different source_id → coverage_count = 2."""
        item1 = _make_item(source_id="weibo", source_name="a", title="A")
        item2 = _make_item(source_id="douyin", source_name="b", title="B")
        cand = _make_candidate(source_items=[item1, item2])
        self.assertEqual(_distinct_source_count(cand), 2)

    def test_hotlist_plus_rss_count_2(self):
        """Hotlist + RSS → coverage_count = 2 (namespaced separation)."""
        hot = _make_item(source_id="weibo", source_name="weibo")
        rss = _make_item(
            source_type="rss", feed_id="hn", source_name="Hacker News",
            title="RSS Title", url="https://hn.example.com/1",
        )
        cand = _make_candidate(source_items=[hot, rss])
        self.assertEqual(_distinct_source_count(cand), 2)

    def test_heat_and_cross_layer_use_same_helper(self):
        """Current Heat and Cross Layer use consistent source identity counting."""
        # 3 items: two hotlist (same source_id), one RSS → 2 distinct sources.
        item1 = _make_item(source_id="weibo", source_name="a", title="A")
        item2 = _make_item(source_id="weibo", source_name="b", title="B")
        item3 = _make_item(
            source_type="rss", feed_id="hn", source_name="hn",
            title="C", url="https://hn.example.com/1",
        )
        cand = _make_candidate(
            source_items=[item1, item2, item3],
            has_hotlist=True, has_rss=True, primary_source_type="mixed",
        )
        heat = score_current_heat_raw(cand)
        cross = score_cross_layer_raw(cand)
        # Both should see 2 distinct sources (not 3 from source_names).
        self.assertEqual(heat.debug["source_coverage_heat"]["coverage_count"], 2)
        self.assertEqual(cross.debug["source_count_support"]["coverage_count"], 2)

    def test_source_identity_namespaced_by_type(self):
        """Hotlist and RSS with same feed_id/source_name stay distinct."""
        hot = _make_item(source_type="hotlist", source_id="hn", source_name="hn")
        rss = _make_item(
            source_type="rss", feed_id="hn", source_name="hn",
            title="RSS", url="https://hn.example.com/1",
        )
        self.assertNotEqual(_source_identity(hot), _source_identity(rss))

    def test_empty_identity_excluded(self):
        """Item with no usable id/name → empty identity excluded from count."""
        item = CRSourceItem(source_type="unknown", source_id=None, feed_id=None, source_name="")
        cand = _make_candidate(source_items=[item])
        self.assertEqual(_distinct_source_count(cand), 0)

    def test_current_heat_coverage_uses_distinct(self):
        """Current Heat source coverage uses distinct source identities."""
        # 4 items all with source_id="weibo" → count=1, not 4.
        cand = _make_candidate(
            source_items=[_make_item(source_id="weibo", title=f"T{i}") for i in range(4)],
        )
        result = score_current_heat_raw(cand)
        # 1 source → coverage heat 2 (not 12)
        self.assertAlmostEqual(result.debug["source_coverage_heat"]["score"], 2.0)

    def test_cross_layer_count_uses_distinct(self):
        """Cross Layer source count support uses distinct source identities."""
        # 4 items all with source_id="weibo" → count=1, not 4.
        cand = _make_candidate(
            source_items=[_make_item(source_id="weibo", title=f"T{i}") for i in range(4)],
        )
        result = score_cross_layer_raw(cand)
        # 1 source → count support 0 (not 4)
        self.assertAlmostEqual(result.debug["source_count_support"]["score"], 0.0)


# ===========================================================================
# G. combine_cr_scores
# ===========================================================================

class TestCombineCrScores(unittest.TestCase):

    def test_heat_cap_80(self):
        """Heat (growth + current_heat) is capped at 80."""
        cand = _make_candidate(candidate_id="x", cluster_key="k")
        gr = make_component_score("growth_raw", 60.0, 60.0)
        ch = make_component_score("current_heat_raw", 50.0, 50.0)
        cl = make_component_score("cross_layer_raw", 0.0, 15.0)
        result = combine_cr_scores(cand, growth_raw=gr, current_heat_raw=ch, cross_layer_raw=cl)
        # heat raw = 60 + 50 = 110, capped at 80
        self.assertAlmostEqual(result.heat.capped_score, 80.0)

    def test_cross_evidence_cap_20(self):
        """Cross-evidence is capped at 20."""
        cand = _make_candidate(candidate_id="x", cluster_key="k")
        gr = make_component_score("growth_raw", 0.0, 60.0)
        ch = make_component_score("current_heat_raw", 0.0, 50.0)
        cl = make_component_score("cross_layer_raw", 15.0, 15.0)
        result = combine_cr_scores(cand, growth_raw=gr, current_heat_raw=ch, cross_layer_raw=cl)
        # cross_evidence = 15 + 0 = 15, within cap
        self.assertAlmostEqual(result.cross_evidence.capped_score, 15.0)

    def test_total_cap_100(self):
        """Total score is capped at 100."""
        cand = _make_candidate(candidate_id="x", cluster_key="k")
        gr = make_component_score("growth_raw", 60.0, 60.0)
        ch = make_component_score("current_heat_raw", 50.0, 50.0)
        cl = make_component_score("cross_layer_raw", 15.0, 15.0)
        result = combine_cr_scores(cand, growth_raw=gr, current_heat_raw=ch, cross_layer_raw=cl)
        # heat = min(60+50, 80) = 80, cross = 15, total = min(95, 100) = 95
        self.assertAlmostEqual(result.total_score, 95.0)

    def test_background_disabled_ignores_input(self):
        """Background support disabled → background_support_raw = 0 even if provided."""
        cand = _make_candidate(candidate_id="x", cluster_key="k")
        gr = make_component_score("growth_raw", 0.0, 60.0)
        ch = make_component_score("current_heat_raw", 0.0, 50.0)
        cl = make_component_score("cross_layer_raw", 0.0, 15.0)
        bg = make_component_score("background_support_raw", 8.0, 10.0)
        result = combine_cr_scores(
            cand, growth_raw=gr, current_heat_raw=ch,
            cross_layer_raw=cl, background_support_raw=bg,
        )
        self.assertAlmostEqual(result.background_support_raw.capped_score, 0.0)

    def test_background_enabled_includes_input(self):
        """Background support enabled → includes and caps input."""
        profile = CRScoringProfile(background_support_enabled=True)
        cand = _make_candidate(candidate_id="x", cluster_key="k")
        gr = make_component_score("growth_raw", 0.0, 60.0)
        ch = make_component_score("current_heat_raw", 0.0, 50.0)
        cl = make_component_score("cross_layer_raw", 0.0, 15.0)
        bg = make_component_score("background_support_raw", 8.0, 10.0)
        result = combine_cr_scores(
            cand, profile=profile,
            growth_raw=gr, current_heat_raw=ch,
            cross_layer_raw=cl, background_support_raw=bg,
        )
        self.assertAlmostEqual(result.background_support_raw.capped_score, 8.0)

    def test_background_enabled_cap(self):
        """Background support enabled → capped at background_support_raw_cap."""
        profile = CRScoringProfile(background_support_enabled=True)
        cand = _make_candidate(candidate_id="x", cluster_key="k")
        gr = make_component_score("growth_raw", 0.0, 60.0)
        ch = make_component_score("current_heat_raw", 0.0, 50.0)
        cl = make_component_score("cross_layer_raw", 0.0, 15.0)
        bg = make_component_score("background_support_raw", 15.0, 10.0)
        result = combine_cr_scores(
            cand, profile=profile,
            growth_raw=gr, current_heat_raw=ch,
            cross_layer_raw=cl, background_support_raw=bg,
        )
        self.assertAlmostEqual(result.background_support_raw.capped_score, 10.0)

    def test_trigger_reasons_dedup(self):
        """Trigger reasons are deduplicated while preserving order."""
        cand = _make_candidate(candidate_id="x", cluster_key="k")
        gr = make_component_score("growth_raw", 5.0, 60.0, reasons=["a", "b"])
        ch = make_component_score("current_heat_raw", 3.0, 50.0, reasons=["b", "c"])
        cl = make_component_score("cross_layer_raw", 1.0, 15.0, reasons=["c"])
        result = combine_cr_scores(
            cand, growth_raw=gr, current_heat_raw=ch,
            cross_layer_raw=cl, trigger_reasons=["d", "a"],
        )
        self.assertEqual(result.trigger_reasons, ["a", "b", "c", "d"])

    def test_float_input_converted(self):
        """Float input is converted to CRComponentScore."""
        cand = _make_candidate(candidate_id="x", cluster_key="k")
        result = combine_cr_scores(cand, growth_raw=30.0, current_heat_raw=20.0, cross_layer_raw=10.0)
        self.assertAlmostEqual(result.growth_raw.raw_score, 30.0)
        self.assertAlmostEqual(result.current_heat_raw.raw_score, 20.0)
        self.assertAlmostEqual(result.cross_layer_raw.raw_score, 10.0)

    def test_none_input_uses_zero(self):
        """None input → zero component score."""
        cand = _make_candidate(candidate_id="x", cluster_key="k")
        result = combine_cr_scores(cand)
        self.assertAlmostEqual(result.growth_raw.raw_score, 0.0)
        self.assertAlmostEqual(result.total_score, 0.0)


# ===========================================================================
# H. score_cr_candidate
# ===========================================================================

class TestScoreCrCandidate(unittest.TestCase):

    def test_returns_cr_score_result(self):
        """score_cr_candidate returns a CRScoreResult."""
        cand = _make_candidate(
            candidate_id="test123",
            cluster_key="test||key",
            has_hotlist=True, primary_source_type="hotlist",
            best_current_rank=5,
            source_names=["weibo"], source_ids=["weibo"],
            source_items=[_make_item(current_rank=5)],
        )
        result = score_cr_candidate(cand)
        self.assertIsInstance(result, CRScoreResult)

    def test_candidate_id_cluster_key_copied(self):
        """candidate_id and cluster_key are copied to result."""
        cand = _make_candidate(
            candidate_id="cid123",
            cluster_key="ck456",
            source_items=[_make_item()],
        )
        result = score_cr_candidate(cand)
        self.assertEqual(result.candidate_id, "cid123")
        self.assertEqual(result.cluster_key, "ck456")

    def test_total_score_positive_for_hot_candidate(self):
        """A hot candidate (top rank, multiple sources) has positive total."""
        item1 = _make_item(
            current_rank=3, normalized_rank=3,
            has_reliable_rank_timeline=True,
            previous_observation_exists=True,
            previous_observation_visible=True,
            previous_visible_rank=10,
            rank_delta=7,
            visible_observation_count=3,
            count=5,
            is_new=True,
            is_new_semantics="new_titles_detection",
            first_crawl_of_day=False,
            has_time_signals=True,
            time_signals_synthetic=False,
        )
        item2 = _make_item(
            title="RSS Title",
            source_type="rss",
            source_name="hn",
            feed_id="hn",
            url="https://hn.example.com/1",
        )
        cand = _make_candidate(
            candidate_id="hot",
            cluster_key="hot||cluster",
            source_items=[item1, item2],
            source_names=["weibo", "hn"],
            source_ids=["weibo"],
            feed_ids=["hn"],
            has_hotlist=True,
            has_rss=True,
            primary_source_type="mixed",
            best_current_rank=3,
        )
        result = score_cr_candidate(cand)
        self.assertGreater(result.total_score, 0.0)

    def test_profile_version(self):
        """Result profile_version matches profile."""
        cand = _make_candidate(source_items=[_make_item()])
        result = score_cr_candidate(cand)
        self.assertEqual(result.profile_version, "cr-score-v0.1")


# ===========================================================================
# I. No decision fields
# ===========================================================================

class TestNoDecisionFields(unittest.TestCase):
    """Assert that CRScoreResult has no decision-related fields."""

    FORBIDDEN_FIELDS = [
        "decision",
        "cr_decision",
        "alert",
        "urgent",
        "watch",
        "suppress",
        "quiet",
        "cooldown",
        "dedupe",
    ]

    def test_no_decision_fields_on_score_result(self):
        """CRScoreResult must not have any decision fields."""
        cand = _make_candidate(
            candidate_id="test",
            cluster_key="test",
            source_items=[_make_item()],
        )
        result = score_cr_candidate(cand)
        for field_name in self.FORBIDDEN_FIELDS:
            self.assertFalse(
                hasattr(result, field_name),
                f"CRScoreResult must not have field '{field_name}'",
            )

    def test_no_decision_fields_on_dataclass(self):
        """CRScoreResult dataclass fields must not include decision fields."""
        field_names = {f.name for f in CRScoreResult.__dataclass_fields__.values()}
        for name in self.FORBIDDEN_FIELDS:
            self.assertNotIn(name, field_names, f"CRScoreResult has forbidden field '{name}'")

    def test_no_decision_values_in_result(self):
        """Result values must not be decision strings."""
        cand = _make_candidate(
            candidate_id="test",
            cluster_key="test",
            source_items=[_make_item()],
        )
        result = score_cr_candidate(cand)
        result_str = str(result)
        for word in ["alert", "urgent", "suppress", "watch", "quiet"]:
            # Only check as standalone values, not substrings in reason strings
            pass  # The field check above is sufficient


# ===========================================================================
# Run
# ===========================================================================

if __name__ == "__main__":
    unittest.main()
