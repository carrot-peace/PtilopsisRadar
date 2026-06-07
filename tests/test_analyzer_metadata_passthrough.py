# coding=utf-8
"""
Focused tests for PR9-pre-a: source metadata pass-through.

Verifies that count_word_frequency() and count_rss_frequency() preserve
source_id / feed_id / published_at / summary / author in title items
without changing existing output semantics.
"""

import importlib.util
import os
import sys
import types
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _ensure_pkg(name, relpath=None):
    real_path = os.path.join(ROOT, relpath) if relpath else None
    if name not in sys.modules:
        m = types.ModuleType(name)
        m.__path__ = [real_path] if real_path else []
        sys.modules[name] = m
    elif real_path and not getattr(sys.modules[name], "__path__", None):
        sys.modules[name].__path__ = [real_path]
    return sys.modules[name]


def _load_file(name, relpath):
    spec = importlib.util.spec_from_file_location(name, os.path.join(ROOT, relpath))
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


# Stub trendradar.utils.time to avoid pytz dependency
_ensure_pkg("trendradar", "trendradar")
_ensure_pkg("trendradar.core", os.path.join("trendradar", "core"))
_ensure_pkg("trendradar.utils", os.path.join("trendradar", "utils"))
if "trendradar.utils.time" not in sys.modules:
    _t = types.ModuleType("trendradar.utils.time")
    _t.DEFAULT_TIMEZONE = "Asia/Shanghai"

    def _stub_format_iso_time(iso_time, timezone="Asia/Shanghai", include_date=True):
        return iso_time[:16] if iso_time else ""

    _t.format_iso_time_friendly = _stub_format_iso_time
    sys.modules["trendradar.utils.time"] = _t

_freq = _load_file("trendradar.core.frequency", "trendradar/core/frequency.py")
_analyzer = _load_file("trendradar.core.analyzer", "trendradar/core/analyzer.py")

count_word_frequency = _analyzer.count_word_frequency
count_rss_frequency = _analyzer.count_rss_frequency


def _group(pattern, display, key=None):
    return {
        "required": [],
        "normal": [_freq._parse_word(pattern)],
        "group_key": key or pattern.strip("/"),
        "display_name": display,
        "max_count": 0,
    }


def _hotlist_title(ranks):
    return {"ranks": ranks, "url": "", "mobileUrl": ""}


# ── Hotlist: source_id pass-through ──────────────────────────────────


class TestHotlistSourceId(unittest.TestCase):
    def test_title_item_includes_source_id(self):
        """count_word_frequency title items preserve source_id."""
        word_groups = [_group("/新闻/", "新闻")]
        results = {
            "weibo": {"重大新闻": _hotlist_title([1])},
            "douyin": {"突发新闻": _hotlist_title([2])},
        }
        stats, _ = count_word_frequency(
            results, word_groups, filter_words=[],
            id_to_name={"weibo": "微博", "douyin": "抖音"},
            mode="daily", quiet=True,
        )
        titles = [t for s in stats for t in s["titles"]]
        self.assertTrue(len(titles) >= 2)
        for t in titles:
            self.assertIn("source_id", t)
        # verify correct source_id per source
        by_sid = {t["source_id"]: t for t in titles}
        self.assertIn("weibo", by_sid)
        self.assertIn("douyin", by_sid)
        self.assertEqual(by_sid["weibo"]["source_name"], "微博")
        self.assertEqual(by_sid["douyin"]["source_name"], "抖音")

    def test_source_id_consistent_with_source_name(self):
        """source_id matches the key in results dict, source_name from id_to_name."""
        word_groups = [_group("/新闻/", "新闻")]
        results = {
            "zhihu": {"某新闻": _hotlist_title([3])},
        }
        stats, _ = count_word_frequency(
            results, word_groups, filter_words=[],
            id_to_name={"zhihu": "知乎"},
            mode="daily", quiet=True,
        )
        title = stats[0]["titles"][0]
        self.assertEqual(title["source_id"], "zhihu")
        self.assertEqual(title["source_name"], "知乎")

    def test_catch_all_title_includes_source_id(self):
        """catch_all synthetic title items also preserve source_id."""
        word_groups = [_group("/裁员/", "经济压力")]
        results = {
            "weibo": {"某地突发爆炸事故": _hotlist_title([1])},
        }
        stats, _ = count_word_frequency(
            results, word_groups, filter_words=[],
            id_to_name={"weibo": "微博"},
            mode="daily", quiet=True,
            catch_all_enabled=True, catch_all_min_rank=5, catch_all_max_items=5,
        )
        synth = [s for s in stats if s["word"].startswith("高热未归类·")]
        self.assertEqual(len(synth), 1)
        title = synth[0]["titles"][0]
        self.assertIn("source_id", title)
        self.assertEqual(title["source_id"], "weibo")


# ── RSS: feed_id + raw metadata pass-through ────────────────────────


class TestRssFeedId(unittest.TestCase):
    def test_title_item_includes_feed_id(self):
        """count_rss_frequency title items preserve feed_id."""
        word_groups = [_group("/AI/", "AI")]
        rss_items = [
            {
                "title": "OpenAI ships GPT-5",
                "feed_id": "openai-news",
                "feed_name": "OpenAI News",
                "url": "https://example.com/1",
                "published_at": "2026-06-07T10:00:00+08:00",
            },
        ]
        stats, _ = count_rss_frequency(rss_items, word_groups, filter_words=[], quiet=True)
        self.assertEqual(len(stats), 1)
        title = stats[0]["titles"][0]
        self.assertEqual(title["feed_id"], "openai-news")
        self.assertEqual(title["source_name"], "OpenAI News")

    def test_feed_id_preserved_when_feed_name_missing(self):
        """feed_id is always set even if feed_name is absent."""
        word_groups = [_group("/test/", "test")]
        rss_items = [
            {
                "title": "test article",
                "feed_id": "my-feed",
                "url": "https://example.com/2",
                "published_at": "2026-06-07T08:00:00+08:00",
            },
        ]
        stats, _ = count_rss_frequency(rss_items, word_groups, filter_words=[], quiet=True)
        title = stats[0]["titles"][0]
        self.assertEqual(title["feed_id"], "my-feed")
        # source_name falls back to feed_id when feed_name is absent
        self.assertEqual(title["source_name"], "my-feed")


class TestRssRawMetadata(unittest.TestCase):
    def _make_item(self, **overrides):
        base = {
            "title": "Test article about AI",
            "feed_id": "test-feed",
            "feed_name": "Test Feed",
            "url": "https://example.com/1",
            "published_at": "2026-06-07T10:00:00+08:00",
        }
        base.update(overrides)
        return base

    def test_published_at_preserved(self):
        """published_at is passed through when available."""
        word_groups = [_group("/AI/", "AI")]
        item = self._make_item(published_at="2026-06-07T10:00:00+08:00")
        stats, _ = count_rss_frequency([item], word_groups, filter_words=[], quiet=True)
        title = stats[0]["titles"][0]
        self.assertEqual(title["published_at"], "2026-06-07T10:00:00+08:00")

    def test_summary_preserved(self):
        """summary is passed through when available."""
        word_groups = [_group("/AI/", "AI")]
        item = self._make_item(summary="A brief summary of the article.")
        stats, _ = count_rss_frequency([item], word_groups, filter_words=[], quiet=True)
        title = stats[0]["titles"][0]
        self.assertEqual(title["summary"], "A brief summary of the article.")

    def test_author_preserved(self):
        """author is passed through when available."""
        word_groups = [_group("/AI/", "AI")]
        item = self._make_item(author="Jane Doe")
        stats, _ = count_rss_frequency([item], word_groups, filter_words=[], quiet=True)
        title = stats[0]["titles"][0]
        self.assertEqual(title["author"], "Jane Doe")

    def test_missing_optional_fields_not_included(self):
        """Optional fields absent from input are not added as empty keys."""
        word_groups = [_group("/AI/", "AI")]
        item = self._make_item()  # no summary, no author
        stats, _ = count_rss_frequency([item], word_groups, filter_words=[], quiet=True)
        title = stats[0]["titles"][0]
        self.assertNotIn("summary", title)
        self.assertNotIn("author", title)
        # published_at IS always present in this fixture, so it should be there
        self.assertIn("published_at", title)

    def test_all_metadata_together(self):
        """All optional metadata preserved in a single item."""
        word_groups = [_group("/AI/", "AI")]
        item = self._make_item(
            published_at="2026-06-07T12:00:00+08:00",
            summary="Full summary here",
            author="John Smith",
        )
        stats, _ = count_rss_frequency([item], word_groups, filter_words=[], quiet=True)
        title = stats[0]["titles"][0]
        self.assertEqual(title["feed_id"], "test-feed")
        self.assertEqual(title["published_at"], "2026-06-07T12:00:00+08:00")
        self.assertEqual(title["summary"], "Full summary here")
        self.assertEqual(title["author"], "John Smith")


# ── Existing semantics unchanged ─────────────────────────────────────


class TestExistingSemanticsPreserved(unittest.TestCase):
    def test_hotlist_existing_fields_unchanged(self):
        """All original fields still present in hotlist title items."""
        word_groups = [_group("/AI/", "AI")]
        results = {"weibo": {"AI 突破": _hotlist_title([1])}}
        stats, _ = count_word_frequency(
            results, word_groups, filter_words=[],
            id_to_name={"weibo": "微博"}, mode="daily", quiet=True,
        )
        title = stats[0]["titles"][0]
        for key in ("title", "source_name", "first_time", "last_time",
                     "time_display", "count", "ranks", "rank_threshold",
                     "url", "mobileUrl", "is_new", "rank_timeline"):
            self.assertIn(key, title)

    def test_rss_existing_fields_unchanged(self):
        """All original fields still present in RSS title items."""
        word_groups = [_group("/AI/", "AI")]
        rss_items = [{
            "title": "AI news",
            "feed_id": "test",
            "feed_name": "Test",
            "url": "https://example.com/1",
            "published_at": "2026-06-07T10:00:00+08:00",
        }]
        stats, _ = count_rss_frequency(rss_items, word_groups, filter_words=[], quiet=True)
        title = stats[0]["titles"][0]
        for key in ("title", "source_name", "time_display", "count",
                     "ranks", "rank_threshold", "url", "mobile_url", "is_new"):
            self.assertIn(key, title)


if __name__ == "__main__":
    unittest.main()
