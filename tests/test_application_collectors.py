import sys
import unittest
from datetime import datetime

# Some legacy tests install partial ``trendradar`` modules during discovery.
# This module exercises the real storage and application packages.
for _stale in [
    _name
    for _name in list(sys.modules)
    if _name == "trendradar" or _name.startswith("trendradar.")
]:
    del sys.modules[_stale]

from trendradar.storage.base import RSSData


class FakeClock:
    def __init__(self):
        self.current = datetime(2026, 7, 24, 9, 30)

    def now(self):
        return self.current

    def date(self):
        return self.current.strftime("%Y-%m-%d")

    def time(self):
        return self.current.strftime("%H-%M")


class FakeHotlistFetcher:
    def __init__(self, events, result):
        self.events = events
        self.result = result

    def crawl_websites(self, ids, interval, domain_rules):
        self.events.append(("fetch", ids, interval, domain_rules))
        return self.result


class FakeRSSFetcher:
    def __init__(self, events, data):
        self.events = events
        self.data = data

    def fetch_all(self):
        self.events.append(("fetch_rss",))
        return self.data


class FakeStorage:
    backend_name = "fake"

    def __init__(self, events, news_saved=True, rss_saved=True):
        self.events = events
        self.news_saved = news_saved
        self.rss_saved = rss_saved

    def save_news_data(self, data):
        self.events.append(("save_news", data))
        return self.news_saved

    def save_txt_snapshot(self, data):
        self.events.append(("snapshot", data))
        return "snapshot.txt" if self.news_saved else None

    def save_rss_data(self, data):
        self.events.append(("save_rss", data))
        return self.rss_saved


class RunStateTests(unittest.TestCase):
    def test_new_run_state_never_reuses_mutable_state(self):
        from trendradar.application.run_state import RunState

        first = RunState.create(
            hotlist_configured_ids={"a"},
            rss_configured_ids={"feed"},
        )
        first.hotlist.successful_ids.add("a")
        first.observed_item_identities.add("identity")

        second = RunState.create(
            hotlist_configured_ids={"a"},
            rss_configured_ids={"feed"},
        )

        self.assertIsNot(first, second)
        self.assertIsNot(first.hotlist, second.hotlist)
        self.assertEqual(second.hotlist.successful_ids, set())
        self.assertEqual(second.observed_item_identities, set())


class HotlistCollectorTests(unittest.TestCase):
    def test_collect_preserves_fetch_save_snapshot_order_and_metadata(self):
        from trendradar.application.collectors import HotlistCollector

        events = []
        fetcher = FakeHotlistFetcher(
            events,
            (
                {
                    "a": {
                        "Alpha": {
                            "url": "https://example.com/a",
                            "rank": 1,
                        }
                    }
                },
                {"a": "Source A", "b": "Source B"},
                ["b"],
            ),
        )
        storage = FakeStorage(events)
        collector = HotlistCollector(fetcher, storage, FakeClock())

        batch = collector.collect(
            platforms=[
                {"id": "a", "name": "Source A", "expected_domain": "example.com"},
                {"id": "b", "name": "Source B"},
            ],
            request_interval=100,
        )

        self.assertEqual(
            [event[0] for event in events],
            ["fetch", "save_news", "snapshot"],
        )
        self.assertTrue(batch.saved)
        self.assertEqual(batch.failed_ids, ("b",))
        self.assertEqual(batch.successful_ids, frozenset({"a"}))
        self.assertEqual(batch.id_to_name["a"], "Source A")
        self.assertEqual(batch.news_data.date, "2026-07-24")
        self.assertEqual(batch.news_data.crawl_time, "09-30")

    def test_save_failure_is_explicit_and_does_not_snapshot(self):
        from trendradar.application.collectors import HotlistCollector

        events = []
        collector = HotlistCollector(
            FakeHotlistFetcher(events, ({}, {}, [])),
            FakeStorage(events, news_saved=False),
            FakeClock(),
        )

        batch = collector.collect([], request_interval=100)

        self.assertFalse(batch.saved)
        self.assertIsNone(batch.snapshot_path)
        self.assertEqual([event[0] for event in events], ["fetch", "save_news"])


class RSSCollectorTests(unittest.TestCase):
    def test_partial_failure_metadata_and_save_result_are_preserved(self):
        from trendradar.application.collectors import RSSCollector

        events = []
        data = RSSData(
            date="2026-07-24",
            crawl_time="09-30",
            items={"good": []},
            id_to_name={"good": "Good", "bad": "Bad"},
            failed_ids=["bad"],
        )
        collector = RSSCollector(
            FakeRSSFetcher(events, data),
            FakeStorage(events, rss_saved=True),
        )

        batch = collector.collect(configured_ids={"good", "bad"})

        self.assertEqual([event[0] for event in events], ["fetch_rss", "save_rss"])
        self.assertTrue(batch.saved)
        self.assertEqual(batch.successful_ids, frozenset({"good"}))
        self.assertEqual(batch.failed_ids, ("bad",))
        self.assertEqual(batch.configured_ids, frozenset({"good", "bad"}))

    def test_save_failure_is_explicit(self):
        from trendradar.application.collectors import RSSCollector

        events = []
        data = RSSData(
            date="2026-07-24",
            crawl_time="09-30",
            items={"feed": []},
        )
        collector = RSSCollector(
            FakeRSSFetcher(events, data),
            FakeStorage(events, rss_saved=False),
        )

        batch = collector.collect(configured_ids={"feed"})

        self.assertFalse(batch.saved)


if __name__ == "__main__":
    unittest.main()
