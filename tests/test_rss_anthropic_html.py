# coding=utf-8

import unittest
import os
import sys
from unittest.mock import Mock, patch

import requests

sys.path.insert(0, os.path.dirname(__file__))
import _bootstrap  # noqa: E402

_bootstrap._ensure_pkg("trendradar")
sys.modules["trendradar"].__path__ = [os.path.join(_bootstrap.ROOT, "trendradar")]
# Clear stale stubs left by other test modules whose module-level code runs during
# pytest collection.  Only clear the modules that directly block the RSS import chain
# to avoid invalidating `import trendradar.__main__ as main` held by other tests.
for _key in [
    "requests",
    "trendradar.crawler",
    "trendradar.crawler.fetcher",
    "trendradar.crawler.rss",
    "trendradar.crawler.rss.fetcher",
    "trendradar.crawler.rss.parser",
    "trendradar.storage",
    "trendradar.storage.base",
    "trendradar.utils",
    "trendradar.utils.time",
]:
    sys.modules.pop(_key, None)
from trendradar.crawler.rss.fetcher import RSSFeedConfig, RSSFetcher


ANTHROPIC_NEWS_HTML = """
<a href="/news/claude-opus-4-8">
  <h2>Introducing Claude Opus 4.8</h2> Product May 28, 2026
  An upgrade to our Opus class of models.
</a>
<a href="/news/services-track-partner-hub">
  Jun 3, 2026 Announcements Introducing the Services Track and Partner Hub
</a>
<a href="/news/claude-opus-4-8">
  May 28, 2026 Product Introducing Claude Opus 4.8
</a>
<a href="/news/claude-design-anthropic-labs">
  Product Apr 17, 2026 <h3>Introducing Claude Design by Anthropic Labs</h3>
  Today, we're launching Claude Design.
</a>
"""


ANTHROPIC_RESEARCH_HTML = """
<a href="/research/team/alignment">Alignment</a>
<a href="/research/natural-language-autoencoders">
  Natural Language Autoencoders: Turning Claude's thoughts into text
  Interpretability May 7, 2026
  AI models like Claude talk in words but think in numbers.
</a>
<a href="/research/coding-agents-social-sciences">
  May 27, 2026 Economic Research Coding agents in the social sciences
</a>
"""


class TestAnthropicHtmlFeed(unittest.TestCase):
    def make_fetcher(self):
        return RSSFetcher(feeds=[], request_interval=0)

    def test_parses_news_cards_and_deduplicates_featured_item(self):
        feed = RSSFeedConfig(
            id="anthropic-news-openrss",
            name="Anthropic News",
            url="https://www.anthropic.com/news",
            source_type="anthropic_html",
            link_prefixes=["/news/"],
        )

        items = self.make_fetcher()._parse_anthropic_html(ANTHROPIC_NEWS_HTML, feed)

        self.assertEqual(len(items), 3)
        self.assertEqual(items[0].title, "Introducing Claude Opus 4.8")
        self.assertEqual(items[0].published_at, "2026-05-28")
        self.assertEqual(items[0].url, "https://www.anthropic.com/news/claude-opus-4-8")
        self.assertIn("Product", items[0].summary)
        self.assertEqual(items[1].title, "Introducing the Services Track and Partner Hub")
        self.assertEqual(items[1].published_at, "2026-06-03")
        self.assertEqual(items[2].title, "Introducing Claude Design by Anthropic Labs")

    def test_parses_research_cards_and_skips_team_links(self):
        feed = RSSFeedConfig(
            id="anthropic-research-openrss",
            name="Anthropic Research",
            url="https://www.anthropic.com/research",
            source_type="anthropic_html",
            link_prefixes=["/research/", "/news/"],
        )

        items = self.make_fetcher()._parse_anthropic_html(ANTHROPIC_RESEARCH_HTML, feed)

        self.assertEqual(len(items), 2)
        self.assertEqual(
            items[0].title,
            "Natural Language Autoencoders: Turning Claude's thoughts into text",
        )
        self.assertEqual(items[0].published_at, "2026-05-07")
        self.assertEqual(items[0].author, "Anthropic")
        self.assertEqual(items[1].title, "Coding agents in the social sciences")
        self.assertEqual(items[1].published_at, "2026-05-27")


class TestRSSFetchRetries(unittest.TestCase):
    def setUp(self):
        self.feed = RSSFeedConfig(
            id="example",
            name="Example Feed",
            url="https://example.com/feed.xml",
        )
        self.fetcher = RSSFetcher(
            feeds=[self.feed],
            request_interval=0,
            max_retries=2,
        )
        self.fetcher.parser.parse = Mock(return_value=[])

    @staticmethod
    def _response():
        response = Mock()
        response.text = "<rss/>"
        response.raise_for_status.return_value = None
        return response

    @staticmethod
    def _http_failure(status_code):
        http_response = requests.Response()
        http_response.status_code = status_code
        response = Mock()
        response.raise_for_status.side_effect = requests.HTTPError(
            f"HTTP {status_code}", response=http_response
        )
        return response

    @patch("trendradar.crawler.rss.fetcher.random.uniform", return_value=0.0)
    @patch("trendradar.crawler.rss.fetcher.time.sleep")
    def test_timeout_retries_twice_then_succeeds(self, sleep, _uniform):
        self.fetcher.session.get = Mock(side_effect=[
            requests.Timeout(),
            requests.Timeout(),
            self._response(),
        ])

        items, error = self.fetcher.fetch_feed(self.feed)

        self.assertEqual(items, [])
        self.assertIsNone(error)
        self.assertEqual(self.fetcher.session.get.call_count, 3)
        self.assertEqual([call.args[0] for call in sleep.call_args_list], [1.0, 2.0])

    @patch("trendradar.crawler.rss.fetcher.random.uniform", return_value=0.0)
    @patch("trendradar.crawler.rss.fetcher.time.sleep")
    def test_connection_error_is_retried(self, sleep, _uniform):
        self.fetcher.session.get = Mock(side_effect=[
            requests.ConnectionError("reset"),
            self._response(),
        ])

        _items, error = self.fetcher.fetch_feed(self.feed)

        self.assertIsNone(error)
        self.assertEqual(self.fetcher.session.get.call_count, 2)
        sleep.assert_called_once_with(1.0)

    @patch("trendradar.crawler.rss.fetcher.random.uniform", return_value=0.0)
    @patch("trendradar.crawler.rss.fetcher.time.sleep")
    def test_429_and_5xx_are_retried(self, sleep, _uniform):
        for status_code in (429, 503):
            with self.subTest(status_code=status_code):
                self.fetcher.session.get = Mock(side_effect=[
                    self._http_failure(status_code),
                    self._response(),
                ])

                _items, error = self.fetcher.fetch_feed(self.feed)

                self.assertIsNone(error)
                self.assertEqual(self.fetcher.session.get.call_count, 2)
        self.assertEqual(sleep.call_count, 2)

    @patch("trendradar.crawler.rss.fetcher.time.sleep")
    def test_non_429_4xx_is_not_retried(self, sleep):
        self.fetcher.session.get = Mock(return_value=self._http_failure(404))

        _items, error = self.fetcher.fetch_feed(self.feed)

        self.assertIn("请求失败", error)
        self.assertEqual(self.fetcher.session.get.call_count, 1)
        sleep.assert_not_called()

    @patch("trendradar.crawler.rss.fetcher.time.sleep")
    def test_parse_error_is_not_retried(self, sleep):
        self.fetcher.session.get = Mock(return_value=self._response())
        self.fetcher.parser.parse = Mock(side_effect=ValueError("invalid feed"))

        _items, error = self.fetcher.fetch_feed(self.feed)

        self.assertEqual(error, "解析失败: invalid feed")
        self.assertEqual(self.fetcher.session.get.call_count, 1)
        sleep.assert_not_called()

    @patch("trendradar.crawler.rss.fetcher.random.uniform", return_value=0.0)
    @patch("trendradar.crawler.rss.fetcher.time.sleep")
    def test_exhausted_retries_return_one_failed_feed(self, sleep, _uniform):
        self.fetcher.session.get = Mock(side_effect=requests.Timeout())

        data = self.fetcher.fetch_all()

        self.assertEqual(self.fetcher.session.get.call_count, 3)
        self.assertEqual(data.failed_ids, [self.feed.id])
        self.assertNotIn(self.feed.id, data.items)
        self.assertEqual(sleep.call_count, 2)

    def test_from_config_defaults_to_two_retries(self):
        fetcher = RSSFetcher.from_config({"feeds": []})
        self.assertEqual(fetcher.max_retries, 2)

    def test_from_config_accepts_retry_override(self):
        fetcher = RSSFetcher.from_config({"feeds": [], "max_retries": 1})
        self.assertEqual(fetcher.max_retries, 1)


if __name__ == "__main__":
    unittest.main()
