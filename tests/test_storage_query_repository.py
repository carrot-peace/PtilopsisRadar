import tempfile
import unittest
from datetime import datetime
from pathlib import Path

from trendradar.storage.base import NewsData, NewsItem, RSSData, RSSItem


class SQLiteQueryRepositoryTests(unittest.TestCase):
    def test_available_dates_rejects_noncanonical_date_filenames(self):
        from trendradar.storage.query import SQLiteQueryRepository

        with tempfile.TemporaryDirectory() as tmp:
            news_dir = Path(tmp) / "news"
            news_dir.mkdir()
            for filename in (
                "2026-07-02.db",
                "2026-7-2.db",
                "2026-02-30.db",
                "notes.db",
            ):
                (news_dir / filename).touch()

            self.assertEqual(
                SQLiteQueryRepository(tmp).available_dates(),
                ["2026-07-02"],
            )

    def test_runtime_and_mcp_read_the_same_news_database(self):
        from mcp_server.services.parser_service import ParserService
        from trendradar.storage.local import LocalStorageBackend
        from trendradar.storage.query import SQLiteQueryRepository

        with tempfile.TemporaryDirectory() as tmp:
            backend = LocalStorageBackend(data_dir=tmp)
            self.assertTrue(
                backend.save_news_data(
                    NewsData(
                        date="2026-07-24",
                        crawl_time="09-30",
                        items={
                            "source": [
                                NewsItem(
                                    title="Shared title",
                                    source_id="source",
                                    rank=1,
                                    url="https://example.com/shared",
                                )
                            ]
                        },
                        id_to_name={"source": "Source"},
                    )
                )
            )
            backend.cleanup()

            repository = SQLiteQueryRepository(tmp)
            parser = ParserService(
                project_root=tmp,
                query_repository=repository,
            )
            titles, names, timestamps = parser.read_all_titles_for_date(
                date=datetime(2026, 7, 24),
                platform_ids=["source"],
            )

            self.assertEqual(names, {"source": "Source"})
            self.assertEqual(
                titles["source"]["Shared title"]["ranks"],
                [1],
            )
            self.assertIn("09-30.db", timestamps)

    def test_repository_reads_rss_with_the_shared_schema(self):
        from trendradar.storage.local import LocalStorageBackend
        from trendradar.storage.query import SQLiteQueryRepository

        with tempfile.TemporaryDirectory() as tmp:
            backend = LocalStorageBackend(data_dir=tmp)
            self.assertTrue(
                backend.save_rss_data(
                    RSSData(
                        date="2026-07-24",
                        crawl_time="09-30",
                        items={
                            "feed": [
                                RSSItem(
                                    title="RSS title",
                                    feed_id="feed",
                                    url="https://example.com/rss",
                                )
                            ]
                        },
                        id_to_name={"feed": "Feed"},
                    )
                )
            )
            backend.cleanup()

            result = SQLiteQueryRepository(tmp).read_snapshot(
                "2026-07-24",
                source_ids=["feed"],
                db_type="rss",
            )

            self.assertIsNotNone(result)
            items, names, timestamps = result
            self.assertEqual(names, {"feed": "Feed"})
            self.assertEqual(
                items["feed"]["RSS title"]["url"],
                "https://example.com/rss",
            )
            self.assertIn("09-30.db", timestamps)


if __name__ == "__main__":
    unittest.main()
