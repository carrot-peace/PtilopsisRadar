"""Public-page adapters: identity, timestamps, pagination and failure semantics."""
import importlib.util
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import Mock

ROOT = Path(__file__).resolve().parents[1]
# Reuse the real RSS chain initialized by the existing RSS adapter tests.
sys.path.insert(0, str(ROOT / "tests"))
import test_rss_anthropic_html as rss_test

RSSFetcher = rss_test.RSSFetcher
RSSFeedConfig = rss_test.RSSFeedConfig
from trendradar.crawler.rss.public_html import account_name, parse_telegram_html, parse_x_public_html


def telegram(posts, cursor=None):
    result = ""
    for post_id, text, timestamp in posts:
        result += f'''<div class="tgme_widget_message" data-post="example/{post_id}">
          <div class="tgme_widget_message_text">{text}</div>
          <a class="tgme_widget_message_date"><time datetime="{timestamp}">date</time></a>
        </div>'''
    if cursor is not None:
        result += f'<a data-before="{cursor}" href="https://untrusted.example/">more</a>'
    return result


def tweet(post_id="42", owner="example", text="男子持刀伤人", millis=1793188800000):
    return {"rest_id": post_id, "core": {"user_results": {"result": {"core": {"screen_name": owner}}}},
            "details": {"full_text": text, "created_at_ms": millis}}


def x_page(posts):
    payload = {"entries": [{"tweet_results": {"result": p}} for p in posts]}
    return '<script>({kind:"GraphQLRequestStream.Completed",value:' + json.dumps(json.dumps(payload)) + '});</script>'


class TestPublicParsers(unittest.TestCase):
    def test_telegram_uses_canonical_ids_unescapes_and_preserves_origin(self):
        page = telegram([(2, '女子被殴打<br>警方介入 &amp; 跟进<a href="https://x.com/example/status/9">查看原文</a>', '2026-10-28T16:00:00+08:00')])
        items, cursor = parse_telegram_html(page, "https://t.me/s/example")
        self.assertIsNone(cursor)
        self.assertEqual(items[0].guid, "https://t.me/example/2")
        self.assertEqual(items[0].title, "女子被殴打")
        self.assertIn("& 跟进", items[0].summary)
        self.assertIn("https://x.com/example/status/9", items[0].summary)
        self.assertEqual(items[0].published_at, "2026-10-28T08:00:00+00:00")

    def test_telegram_deduplicates_album_and_sorts_before_cap(self):
        page = telegram([(1, '', '2026-10-27T08:00:00Z'), (1, '完整说明', '2026-10-27T08:00:00Z'), (2, '新消息', '2026-10-28T08:00:00Z')], cursor=1)
        items, cursor = parse_telegram_html(page, "https://t.me/s/example")
        self.assertEqual(cursor, 1)
        self.assertEqual([i.title for i in items], ["新消息", "完整说明"])

    def test_telegram_media_only_is_retained_as_uninterpreted_message(self):
        items, _ = parse_telegram_html(telegram([(1, '', '2026-10-28T08:00:00Z')]), 'https://t.me/s/example')
        self.assertEqual(items[0].title, '图片或视频消息')

    def test_empty_or_wrong_channel_is_not_healthy_zero(self):
        for page in ['<html>Login</html>', telegram([(1, 'text', '2026-10-28T08:00:00Z')]).replace('example/', 'another/')]:
            with self.subTest(page=page), self.assertRaises(ValueError):
                parse_telegram_html(page, 'https://t.me/s/example')

    def test_undated_messages_fail_instead_of_getting_crawl_time(self):
        for date in ['', '2026-10-28T08:00:00', 'nonsense']:
            with self.subTest(date=date), self.assertRaises(ValueError):
                parse_telegram_html(telegram([(1, 'text', date)]), 'https://t.me/s/example')

    def test_noncanonical_or_untrusted_urls_are_rejected(self):
        for url, kind in [('http://t.me/s/example', 'telegram_html'), ('https://evil.example/s/example', 'telegram_html'), ('https://t.me/s/example?before=1', 'telegram_html'), ('https://t.me/s/example/42', 'telegram_html'), ('https://x.com@evil.example/example', 'x_public_html'), ('https://x.com/example/status/42', 'x_public_html')]:
            with self.subTest(url=url), self.assertRaises(ValueError):
                account_name(url, kind)

    def test_x_keeps_long_posts_and_ignores_quoted_posts(self):
        main = tweet()
        main['note_tweet'] = {'note_tweet_results': {'result': {'text': '完整长文\n' + '证据' * 400}}}
        main['quoted_tweet_results'] = {'result': tweet('99', text='被引用原帖')}
        items = parse_x_public_html(x_page([main]), 'https://x.com/example')
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0].title, '完整长文')
        self.assertEqual(len(items[0].summary), 500)
        self.assertEqual(items[0].url, 'https://x.com/example/status/42')

    def test_x_does_not_emit_another_accounts_posts(self):
        items = parse_x_public_html(x_page([tweet(), tweet('43', owner='another')]), 'https://x.com/example')
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0].author, 'example')

    def test_x_deduplicates_and_orders_old_pin_after_current_posts(self):
        page = x_page([tweet('1', millis=1600000000000), tweet('2'), tweet('2')])
        items = parse_x_public_html(page, 'https://x.com/example')
        self.assertEqual([i.guid for i in items], ['https://x.com/example/status/2', 'https://x.com/example/status/1'])

    def test_x_login_or_changed_renderer_is_a_failure(self):
        for page in ['<html>Sign in</html>', '<script>value:"not-json"</script>', x_page([tweet(owner='another')])]:
            with self.subTest(page=page), self.assertRaises(ValueError):
                parse_x_public_html(page, 'https://x.com/example')

    def test_x_missing_timestamp_is_not_assigned_current_time(self):
        post = tweet(); post['details'].pop('created_at_ms')
        with self.assertRaises(ValueError):
            parse_x_public_html(x_page([post]), 'https://x.com/example')


class TestPublicFetcher(unittest.TestCase):
    def make_fetcher(self):
        return RSSFetcher(feeds=[], request_interval=0, max_retries=0)

    @staticmethod
    def response(text):
        return Mock(text=text, raise_for_status=Mock())

    def test_telegram_pagination_is_bounded_and_does_not_follow_href(self):
        fetcher = self.make_fetcher()
        feed = RSSFeedConfig('example', 'Example', 'https://t.me/s/example', source_type='telegram_html', max_pages=2, max_items=2)
        fetcher.session.get = Mock(side_effect=[self.response(telegram([(3, 'new', '2026-10-28T10:00:00Z')], 3)), self.response(telegram([(2, 'old', '2026-10-28T09:00:00Z')], 2))])
        items, error = fetcher.fetch_feed(feed)
        self.assertIsNone(error)
        self.assertEqual(len(items), 2)
        self.assertEqual(fetcher.session.get.call_args_list[1].args, ('https://t.me/s/example',))
        self.assertEqual(fetcher.session.get.call_args_list[1].kwargs['params'], {'before': 3})
        self.assertEqual(fetcher.session.get.call_count, 2)

    def test_nonadvancing_pagination_is_reported_as_failure(self):
        fetcher = self.make_fetcher()
        page = telegram([(3, 'new', '2026-10-28T10:00:00Z')], 3)
        fetcher.session.get = Mock(return_value=self.response(page))
        feed = RSSFeedConfig('example', 'Example', 'https://t.me/s/example', source_type='telegram_html', max_pages=2)
        items, error = fetcher.fetch_feed(feed)
        self.assertEqual(items, [])
        self.assertIn('pagination', error)

    def test_parse_failure_marks_feed_failed_in_collection_health(self):
        feed = RSSFeedConfig('example', 'Example', 'https://x.com/example', source_type='x_public_html')
        fetcher = self.make_fetcher(); fetcher.feeds = [feed]
        fetcher.session.get = Mock(return_value=self.response('<html>Login</html>'))
        result = fetcher.fetch_all()
        self.assertEqual(result.failed_ids, ['example'])
        self.assertNotIn('example', result.items)

    def test_rejects_wrong_origin_before_request(self):
        fetcher = self.make_fetcher(); fetcher.session.get = Mock()
        feed = RSSFeedConfig('example', 'Example', 'https://evil.example/', source_type='telegram_html')
        _, error = fetcher.fetch_feed(feed)
        self.assertIsNotNone(error)
        fetcher.session.get.assert_not_called()

    def test_from_config_preserves_pages_and_disabled_candidates(self):
        fetcher = RSSFetcher.from_config({'feeds': [
            {'id': 'one', 'name': 'One', 'url': 'https://t.me/s/example', 'source_type': 'telegram_html', 'max_pages': 3},
            {'id': 'two', 'name': 'Two', 'url': 'https://x.com/example', 'source_type': 'x_public_html', 'enabled': False},
        ]})
        self.assertEqual(len(fetcher.feeds), 1)
        self.assertEqual(fetcher.feeds[0].max_pages, 3)


if __name__ == '__main__':
    unittest.main()
