# coding=utf-8
"""
CR cross-evidence RSS admission tests (funnel stage 1) + end-to-end funnel.

Covers select_cross_evidence_rss admission/window/flood/cap/output-shape, and
the full funnel through build_cr_pipeline_from_primitives:
  admit (loose) -> Rule 4 merge (strict) -> drop unmerged RSS.
Including the decoupling proof: a Hormuz-style item is admitted but, sharing
only a stoplisted entity, is NOT merged and is dropped — showing "starvation"
(stage 1) and "merge precision" (stage 2) are separate concerns.
"""

import os
import sys
import unittest
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from trendradar.cr.cross_evidence_ingest import (
    build_cross_evidence_cluster_config_from_env,
    merge_rss_stats,
    select_cross_evidence_rss,
)
from trendradar.cr.entity_match import EntityResources
from trendradar.cr.adapter import adapt_rss_stats
from trendradar.cr.models import (
    CRClusterConfig,
    CRPrimitiveRecord,
    CRRunContext,
    CRSourceItem,
)
from trendradar.cr.pipeline import (
    CRPipelineConfig,
    build_cr_pipeline_from_primitives,
)


_RES = EntityResources(
    dictionary={"海力士": "hynix", "霍尔木兹": "hormuz", "伊朗": "iran"},
    stoplist={"hormuz", "iran"},
)

_TZ = timezone(timedelta(hours=8))
_NOW = datetime(2026, 6, 19, 12, 0, 0, tzinfo=_TZ)

_HOTLIST_TITLES = ["SK海力士HBM4E量产", "霍尔木兹海峡重开提振股债"]


def _rss(title, *, feed_id="reuters", feed_name="Reuters",
         url=None, published_at="2026-06-19T10:00:00+08:00"):
    return {
        "title": title, "feed_id": feed_id, "feed_name": feed_name,
        "url": url or f"https://rss.example.com/{abs(hash(title)) % 10000}",
        "published_at": published_at, "summary": "", "author": "",
    }


def _admitted_titles(raw, **kw):
    kw.setdefault("resources", _RES)
    kw.setdefault("now", _NOW)
    groups = select_cross_evidence_rss(raw, _HOTLIST_TITLES, **kw)
    if not groups:
        return []
    return [t["title"] for t in groups[0]["titles"]]


class TestAdmission(unittest.TestCase):
    def test_admits_on_entity_overlap(self):
        out = _admitted_titles([_rss("SK Hynix starts HBM4E mass production")])
        self.assertEqual(out, ["SK Hynix starts HBM4E mass production"])

    def test_drops_zero_overlap(self):
        out = _admitted_titles([_rss("Why Accenture Stock Opened Lower")])
        self.assertEqual(out, [])

    def test_admits_on_single_stoplisted_overlap(self):
        # Hormuz shares only the stoplisted 'hormuz' — admission is loose and
        # still lets it in (merge precision is Rule 4's job, not admission's).
        out = _admitted_titles([_rss("Normal shipping will not resume in strait of Hormuz")])
        self.assertEqual(len(out), 1)

    def test_time_window_drops_old(self):
        old = _rss("SK Hynix HBM4E recap", published_at="2026-06-16T00:00:00+08:00")  # ~60h old
        self.assertEqual(_admitted_titles([old], window_hours=36.0), [])

    def test_naive_timestamp_is_interpreted_as_utc(self):
        item = _rss(
            "SK Hynix HBM4E recap",
            published_at="2026-06-17T23:00:00",
        )
        self.assertEqual(
            _admitted_titles([item], window_hours=36.0),
            ["SK Hynix HBM4E recap"],
        )

    def test_unparseable_published_at_kept(self):
        # Lenient: raw_rss_items is already per-feed age-filtered upstream.
        item = _rss("SK Hynix HBM4E note", published_at="not-a-date")
        self.assertEqual(len(_admitted_titles([item])), 1)

    def test_empty_hotlist_returns_empty(self):
        groups = select_cross_evidence_rss(
            [_rss("SK Hynix HBM4E")], [], resources=_RES, now=_NOW
        )
        self.assertEqual(groups, [])

    def test_common_entity_flood_all_admitted(self):
        # A common entity admits many topically-related items (the flood the
        # post-cluster drop later evaporates).  Here: all admitted at stage 1.
        raw = [_rss(f"Hormuz update number {i} ongoing") for i in range(6)]
        self.assertEqual(len(_admitted_titles(raw)), 6)

    def test_max_per_topic_cap(self):
        raw = [_rss(f"SK Hynix HBM4E item {i}") for i in range(5)]
        out = _admitted_titles(raw, max_per_topic=2)
        self.assertEqual(len(out), 2)

    def test_output_shape_consumable_by_adapter(self):
        raw = _rss("SK Hynix starts HBM4E mass production", feed_name="Reuters")
        raw["summary"] = "Production has started"
        raw["author"] = "Reporter"
        groups = select_cross_evidence_rss(
            [raw],
            _HOTLIST_TITLES, resources=_RES, now=_NOW,
        )
        prims = adapt_rss_stats(groups, context=CRRunContext(mode="daily"))
        self.assertEqual(len(prims), 1)
        item = prims[0].source_items[0]
        self.assertEqual(item.source_type, "rss")
        self.assertEqual(item.source_name, "Reuters")   # feed_name -> source_name
        self.assertEqual(item.feed_id, "reuters")
        self.assertEqual(item.summary, "Production has started")
        self.assertEqual(item.author, "Reporter")
        self.assertTrue(item.cross_evidence_admitted)

    def test_merge_preserves_keyword_rss_and_deduplicates_admitted(self):
        keyword_item = {
            "title": "中文关键词 RSS",
            "feed_id": "feed-a",
            "url": "https://rss.example.com/existing",
        }
        admitted_duplicate = {
            **keyword_item,
            "cross_evidence_admitted": True,
        }
        admitted_new = {
            "title": "English corroboration",
            "feed_id": "feed-b",
            "url": "https://rss.example.com/new",
            "cross_evidence_admitted": True,
        }
        keyword = [{"word": "关键词", "titles": [keyword_item]}]
        admitted = [{"word": None, "titles": [admitted_duplicate, admitted_new]}]

        merged = merge_rss_stats(keyword, admitted)

        self.assertEqual([g["word"] for g in merged], ["关键词", None])
        self.assertEqual(merged[0]["titles"], [keyword_item])
        self.assertEqual(merged[1]["titles"], [admitted_new])
        self.assertEqual(keyword[0]["titles"], [keyword_item])


class TestCrossEvidenceConfig(unittest.TestCase):
    def test_all_runtime_knobs_are_resolved(self):
        cfg = build_cross_evidence_cluster_config_from_env({
            "PTILOPSIS_CR_CROSS_EVIDENCE_RSS_ENABLED": "false",
            "PTILOPSIS_CR_CROSS_EVIDENCE_WINDOW_HOURS": "12.5",
            "PTILOPSIS_CR_CROSS_EVIDENCE_MAX_PER_TOPIC": "7",
            "PTILOPSIS_CR_DROP_UNMERGED_RSS": "true",
        })
        self.assertFalse(cfg.cross_evidence_rss_enabled)
        self.assertEqual(cfg.cross_evidence_window_hours, 12.5)
        self.assertEqual(cfg.cross_evidence_max_per_topic, 7)
        self.assertTrue(cfg.drop_unmerged_rss)

    def test_disabling_admission_restores_legacy_drop_default(self):
        cfg = build_cross_evidence_cluster_config_from_env({
            "PTILOPSIS_CR_CROSS_EVIDENCE_RSS_ENABLED": "0",
        })
        self.assertFalse(cfg.cross_evidence_rss_enabled)
        self.assertFalse(cfg.drop_unmerged_rss)


class TestFunnelEndToEnd(unittest.TestCase):
    """admit (loose) -> Rule 4 merge (strict) -> drop unmerged RSS."""

    def _hotlist_prim(self, title, rank):
        return CRPrimitiveRecord(
            keyword_group="kw",
            keyword_groups=["kw"],
            source_items=[CRSourceItem(
                source_type="hotlist", source_id="weibo", source_name="weibo",
                title=title, url=f"https://hl.example.com/{rank}",
                current_rank=rank, normalized_rank=rank, is_visible=True,
            )],
        )

    def test_merge_and_drop(self):
        hotlist = [
            self._hotlist_prim("SK海力士HBM4E量产", 3),
            self._hotlist_prim("霍尔木兹海峡重开提振股债", 5),
        ]
        raw = [
            _rss("SK Hynix starts HBM4E mass production"),            # → merges (hynix, hbm4e)
            _rss("Normal shipping will not resume in strait of Hormuz"),  # admitted, won't merge
            _rss("Why Accenture Stock Opened Lower"),                  # never admitted
        ]
        groups = select_cross_evidence_rss(raw, _HOTLIST_TITLES, resources=_RES, now=_NOW)
        rss_prims = adapt_rss_stats(groups, context=CRRunContext(mode="daily"))

        cfg = CRPipelineConfig(cluster=CRClusterConfig(
            entity_resources=_RES,
            drop_unmerged_rss=True,
        ))
        result = build_cr_pipeline_from_primitives(
            list(hotlist) + list(rss_prims), run_label="t", config=cfg,
        )
        types = sorted(c.primary_source_type for c in result.candidates)
        # SK Hynix -> mixed; Hormuz hotlist stays hotlist-only; no RSS-only survives.
        self.assertEqual(types, ["hotlist", "mixed"])
        mixed = [c for c in result.candidates if c.primary_source_type == "mixed"]
        self.assertEqual(len(mixed), 1)
        self.assertTrue(mixed[0].has_hotlist and mixed[0].has_rss)
        self.assertNotIn("rss", types)  # decoupling: admitted-but-unmerged Hormuz RSS dropped

    def test_keyword_rss_only_candidate_is_not_dropped(self):
        groups = [{
            "word": "关键词",
            "titles": [{
                "title": "Legacy keyword RSS",
                "source_name": "Feed",
                "feed_id": "feed",
                "url": "https://rss.example.com/legacy",
                "count": 1,
                "ranks": [],
            }],
        }]
        rss_prims = adapt_rss_stats(groups, context=CRRunContext(mode="daily"))
        cfg = CRPipelineConfig(cluster=CRClusterConfig(drop_unmerged_rss=True))

        result = build_cr_pipeline_from_primitives(
            list(rss_prims), run_label="t", config=cfg,
        )

        self.assertEqual(len(result.candidates), 1)
        self.assertEqual(result.candidates[0].primary_source_type, "rss")


if __name__ == "__main__":
    unittest.main()
