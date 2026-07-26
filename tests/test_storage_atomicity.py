import tempfile
import unittest
from pathlib import Path

from trendradar.storage.base import NewsData, NewsItem, RSSData, RSSItem
from trendradar.storage.local import LocalStorageBackend


class StorageAtomicityTestCase(unittest.TestCase):
    date = "2026-07-24"

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.backend = LocalStorageBackend(
            data_dir=str(Path(self.temp_dir.name) / "output"),
            enable_txt=False,
            enable_html=False,
        )
        self.addCleanup(self.backend.cleanup)

    @staticmethod
    def _table_counts(connection, table_names):
        return {
            table_name: connection.execute(
                f"SELECT COUNT(*) FROM {table_name}"
            ).fetchone()[0]
            for table_name in table_names
        }

    def assert_connection_pragmas(self):
        for db_type in ("news", "rss"):
            with self.subTest(db_type=db_type):
                connection = self.backend._get_connection(
                    self.date,
                    db_type=db_type,
                )
                self.assertEqual(
                    connection.execute("PRAGMA foreign_keys").fetchone()[0],
                    1,
                )
                self.assertEqual(
                    connection.execute("PRAGMA busy_timeout").fetchone()[0],
                    5000,
                )


class StorageConnectionConfigurationTests(StorageAtomicityTestCase):
    def test_connections_enable_foreign_keys_and_busy_timeout(self):
        self.assert_connection_pragmas()


class NewsStorageAtomicityTests(StorageAtomicityTestCase):
    tables = (
        "platforms",
        "news_items",
        "rank_history",
        "crawl_records",
        "crawl_source_status",
    )

    def test_item_failure_rolls_back_entire_batch_and_connection_recovers(self):
        connection = self.backend._get_connection(self.date)
        connection.executescript(
            """
            CREATE TRIGGER fail_second_news
            BEFORE INSERT ON news_items
            WHEN NEW.title = 'boom'
            BEGIN
                SELECT RAISE(ABORT, 'injected failure');
            END;
            """
        )
        connection.commit()

        failed_batch = NewsData(
            date=self.date,
            crawl_time="09-00",
            items={
                "source": [
                    NewsItem(
                        title="good",
                        source_id="source",
                        rank=1,
                        url="https://example.com/good",
                    ),
                    NewsItem(
                        title="boom",
                        source_id="source",
                        rank=2,
                        url="https://example.com/boom",
                    ),
                ]
            },
            id_to_name={"source": "Source"},
        )

        self.assertFalse(self.backend.save_news_data(failed_batch))
        self.assertEqual(
            self._table_counts(connection, self.tables),
            {table_name: 0 for table_name in self.tables},
        )

        recovered_batch = NewsData(
            date=self.date,
            crawl_time="09-05",
            items={
                "source": [
                    NewsItem(
                        title="recovered",
                        source_id="source",
                        rank=1,
                        url="https://example.com/recovered",
                    )
                ]
            },
            id_to_name={"source": "Source"},
        )

        self.assertTrue(self.backend.save_news_data(recovered_batch))
        self.assertEqual(
            self._table_counts(connection, self.tables),
            {
                "platforms": 1,
                "news_items": 1,
                "rank_history": 1,
                "crawl_records": 1,
                "crawl_source_status": 1,
            },
        )


class RSSStorageAtomicityTests(StorageAtomicityTestCase):
    tables = (
        "rss_feeds",
        "rss_items",
        "rss_crawl_records",
        "rss_crawl_status",
    )

    def test_item_failure_rolls_back_entire_batch_and_connection_recovers(self):
        connection = self.backend._get_connection(self.date, db_type="rss")
        connection.executescript(
            """
            CREATE TRIGGER fail_second_rss
            BEFORE INSERT ON rss_items
            WHEN NEW.title = 'boom'
            BEGIN
                SELECT RAISE(ABORT, 'injected failure');
            END;
            """
        )
        connection.commit()

        failed_batch = RSSData(
            date=self.date,
            crawl_time="09-00",
            items={
                "feed": [
                    RSSItem(
                        title="good",
                        feed_id="feed",
                        url="https://example.com/good",
                    ),
                    RSSItem(
                        title="boom",
                        feed_id="feed",
                        url="https://example.com/boom",
                    ),
                ]
            },
            id_to_name={"feed": "Feed"},
        )

        self.assertFalse(self.backend.save_rss_data(failed_batch))
        self.assertEqual(
            self._table_counts(connection, self.tables),
            {table_name: 0 for table_name in self.tables},
        )

        recovered_batch = RSSData(
            date=self.date,
            crawl_time="09-05",
            items={
                "feed": [
                    RSSItem(
                        title="recovered",
                        feed_id="feed",
                        url="https://example.com/recovered",
                    )
                ]
            },
            id_to_name={"feed": "Feed"},
        )

        self.assertTrue(self.backend.save_rss_data(recovered_batch))
        self.assertEqual(
            self._table_counts(connection, self.tables),
            {
                "rss_feeds": 1,
                "rss_items": 1,
                "rss_crawl_records": 1,
                "rss_crawl_status": 1,
            },
        )


class AIStorageAtomicityTests(StorageAtomicityTestCase):
    def test_tag_batch_failure_rolls_back_every_tag(self):
        connection = self.backend._get_connection(self.date)
        connection.executescript(
            """
            CREATE TRIGGER fail_second_tag
            BEFORE INSERT ON ai_filter_tags
            WHEN NEW.tag = 'boom'
            BEGIN
                SELECT RAISE(ABORT, 'injected failure');
            END;
            """
        )
        connection.commit()

        saved = self.backend.save_ai_filter_tags(
            [{"tag": "good"}, {"tag": "boom"}],
            version=1,
            prompt_hash="hash",
            date=self.date,
        )

        self.assertEqual(saved, 0)
        self.assertEqual(
            connection.execute("SELECT COUNT(*) FROM ai_filter_tags").fetchone()[0],
            0,
        )

        saved = self.backend.save_ai_filter_tags(
            [{"tag": "recovered"}],
            version=2,
            prompt_hash="hash-2",
            date=self.date,
        )
        self.assertEqual(saved, 1)

    def test_analyzed_news_failure_rolls_back_every_record(self):
        connection = self.backend._get_connection(self.date)
        connection.executescript(
            """
            CREATE TRIGGER fail_second_analyzed_news
            BEFORE INSERT ON ai_filter_analyzed_news
            WHEN NEW.news_item_id = 2
            BEGIN
                SELECT RAISE(ABORT, 'injected failure');
            END;
            """
        )
        connection.commit()

        saved = self.backend.save_analyzed_news(
            [1, 2],
            source_type="hotlist",
            interests_file="ai_interests.txt",
            prompt_hash="hash",
            matched_ids={1},
            date=self.date,
        )

        self.assertEqual(saved, 0)
        self.assertEqual(
            connection.execute(
                "SELECT COUNT(*) FROM ai_filter_analyzed_news"
            ).fetchone()[0],
            0,
        )

        saved = self.backend.save_analyzed_news(
            [3],
            source_type="hotlist",
            interests_file="ai_interests.txt",
            prompt_hash="hash",
            matched_ids=set(),
            date=self.date,
        )
        self.assertEqual(saved, 1)

    def test_filter_result_failure_rolls_back_every_result(self):
        connection = self.backend._get_connection(self.date)
        connection.executescript(
            """
            CREATE TRIGGER fail_second_filter_result
            BEFORE INSERT ON ai_filter_results
            WHEN NEW.news_item_id = 2
            BEGIN
                SELECT RAISE(ABORT, 'injected failure');
            END;
            """
        )
        connection.commit()

        saved = self.backend.save_ai_filter_results(
            [
                {"news_item_id": 1, "tag_id": 1},
                {"news_item_id": 2, "tag_id": 1},
            ],
            date=self.date,
        )

        self.assertEqual(saved, 0)
        self.assertEqual(
            connection.execute("SELECT COUNT(*) FROM ai_filter_results").fetchone()[0],
            0,
        )

        saved = self.backend.save_ai_filter_results(
            [{"news_item_id": 3, "tag_id": 1}],
            date=self.date,
        )
        self.assertEqual(saved, 1)
        self.assertEqual(
            self.backend.save_ai_filter_results(
                [{"news_item_id": 3, "tag_id": 1}],
                date=self.date,
            ),
            0,
        )

    def test_deprecation_failure_restores_tags_and_results(self):
        connection = self.backend._get_connection(self.date)
        connection.executescript(
            """
            INSERT INTO ai_filter_tags
                (id, tag, version, prompt_hash, interests_file, created_at)
            VALUES
                (1, 'tag-1', 1, 'hash', 'ai_interests.txt', 'now'),
                (2, 'tag-2', 1, 'hash', 'ai_interests.txt', 'now');
            INSERT INTO ai_filter_results
                (news_item_id, source_type, tag_id, created_at)
            VALUES
                (1, 'hotlist', 1, 'now'),
                (2, 'hotlist', 2, 'now');
            CREATE TRIGGER fail_result_deprecation
            BEFORE UPDATE ON ai_filter_results
            WHEN OLD.news_item_id = 2
            BEGIN
                SELECT RAISE(ABORT, 'injected failure');
            END;
            """
        )
        connection.commit()

        deprecated = self.backend.deprecate_all_ai_filter_tags(date=self.date)

        self.assertEqual(deprecated, 0)
        self.assertEqual(
            [
                row[0]
                for row in connection.execute(
                    "SELECT DISTINCT status FROM ai_filter_tags"
                ).fetchall()
            ],
            ["active"],
        )
        self.assertEqual(
            [
                row[0]
                for row in connection.execute(
                    "SELECT DISTINCT status FROM ai_filter_results"
                ).fetchall()
            ],
            ["active"],
        )


class PeriodExecutionAtomicityTests(StorageAtomicityTestCase):
    def test_failed_record_does_not_poison_connection(self):
        connection = self.backend._get_connection(self.date)
        connection.executescript(
            """
            CREATE TRIGGER fail_period_record
            BEFORE INSERT ON period_executions
            WHEN NEW.period_key = 'boom'
            BEGIN
                SELECT RAISE(ABORT, 'injected failure');
            END;
            """
        )
        connection.commit()

        self.assertFalse(
            self.backend.record_period_execution(self.date, "boom", "analyze")
        )
        self.assertEqual(
            connection.execute("SELECT COUNT(*) FROM period_executions").fetchone()[0],
            0,
        )
        self.assertTrue(
            self.backend.record_period_execution(self.date, "recovered", "analyze")
        )
        self.assertTrue(
            self.backend.has_period_executed(self.date, "recovered", "analyze")
        )


if __name__ == "__main__":
    unittest.main()
