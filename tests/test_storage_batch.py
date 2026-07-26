import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from tests.test_remote_storage_cas import VersionedFakeS3, client_error
from trendradar.ai.filter import AIFilterResult
from trendradar.context import AppContext
from trendradar.storage.base import NewsData, NewsItem, RSSData, RSSItem
from trendradar.storage.local import LocalStorageBackend
from trendradar.storage.remote import RemoteStorageBackend
from trendradar.storage.results import WriteResult


class LocalStorageBatchTests(unittest.TestCase):
    date = "2026-07-24"

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.backend = LocalStorageBackend(data_dir=self.temp_dir.name)
        self.addCleanup(self.backend.cleanup)

    def test_user_exception_rolls_back_all_mutations(self):
        with self.assertRaisesRegex(RuntimeError, "injected"):
            with self.backend.batch():
                self.backend.save_ai_filter_tags(
                    [{"tag": "first"}],
                    1,
                    "hash",
                    date=self.date,
                )
                self.backend.save_ai_filter_tags(
                    [{"tag": "second"}],
                    1,
                    "hash",
                    date=self.date,
                )
                self.assertEqual(
                    len(self.backend.get_active_ai_filter_tags(self.date)),
                    2,
                )
                raise RuntimeError("injected")

        self.assertEqual(self.backend.get_active_ai_filter_tags(self.date), [])

    def test_normal_exit_commits_and_exposes_result(self):
        with self.backend.batch() as batch:
            self.backend.save_ai_filter_tags(
                [{"tag": "kept"}],
                1,
                "hash",
                date=self.date,
            )

        self.assertTrue(batch.result.committed)
        self.assertEqual(
            [tag["tag"] for tag in self.backend.get_active_ai_filter_tags(self.date)],
            ["kept"],
        )

    def test_nested_batch_is_rejected_and_outer_batch_rolls_back(self):
        with self.assertRaisesRegex(RuntimeError, "Nested"):
            with self.backend.batch():
                self.backend.save_ai_filter_tags(
                    [{"tag": "discarded"}],
                    1,
                    "hash",
                    date=self.date,
                )
                with self.backend.batch():
                    pass

        self.assertEqual(self.backend.get_active_ai_filter_tags(self.date), [])

    def test_caught_repository_failure_marks_outer_batch_for_rollback(self):
        connection = self.backend._get_connection(self.date)
        connection.executescript(
            """
            CREATE TRIGGER fail_second_tag_in_batch
            BEFORE INSERT ON ai_filter_tags
            WHEN NEW.tag = 'boom'
            BEGIN
                SELECT RAISE(ABORT, 'injected failure');
            END;
            """
        )
        connection.commit()

        with self.backend.batch() as batch:
            saved = self.backend.save_ai_filter_tags(
                [{"tag": "good"}, {"tag": "boom"}],
                1,
                "hash",
                date=self.date,
            )
            self.assertEqual(saved, 0)

        self.assertFalse(batch.result.committed)
        self.assertTrue(batch.result.rolled_back)
        self.assertEqual(self.backend.get_active_ai_filter_tags(self.date), [])


class AIFilterBatchLifecycleTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.backend = LocalStorageBackend(data_dir=self.temp_dir.name)
        self.addCleanup(self.backend.cleanup)
        self.context = AppContext({"FILTER": {"METHOD": "ai"}})
        self.context._storage_manager = self.backend

    def test_ai_exception_rolls_back_storage_batch(self):
        def failing_workflow(_interests_file):
            self.backend.save_ai_filter_tags(
                [{"tag": "discarded"}],
                1,
                "hash",
            )
            raise RuntimeError("classify failed")

        self.context._run_ai_filter_impl = failing_workflow
        with self.assertRaisesRegex(RuntimeError, "classify failed"):
            self.context.run_ai_filter()

        self.assertEqual(self.backend.get_active_ai_filter_tags(), [])
        with self.backend.batch():
            pass

    def test_ai_early_failure_rolls_back_cleanly(self):
        def early_return(_interests_file):
            self.backend.save_ai_filter_tags(
                [{"tag": "discarded"}],
                1,
                "hash",
            )
            return AIFilterResult(success=False, error="extract failed")

        self.context._run_ai_filter_impl = early_return
        result = self.context.run_ai_filter()

        self.assertEqual(result.error, "extract failed")
        self.assertEqual(self.backend.get_active_ai_filter_tags(), [])


class RemoteStorageBatchCompatibilityTests(unittest.TestCase):
    @staticmethod
    def _backend():
        backend = object.__new__(RemoteStorageBackend)
        backend._batch_mode = False
        backend._batch_dirty = set()
        return backend

    def test_remote_wrappers_consume_typed_write_results(self):
        backend = self._backend()
        connection = sqlite3.connect(":memory:")
        self.addCleanup(connection.close)
        connection.execute("CREATE TABLE news_items (id INTEGER PRIMARY KEY)")
        backend._get_connection = lambda *_args, **_kwargs: connection
        backend._upload_sqlite = lambda *_args, **_kwargs: True
        backend._execute_remote_mutation = (
            lambda _date, _db_type, operation, _should_upload: (
                operation(),
                True,
            )
        )
        backend._save_news_data_impl = lambda *_args: WriteResult(
            committed=True,
            inserted=2,
        )
        backend._save_rss_data_impl = lambda *_args: WriteResult(
            committed=True,
            inserted=3,
        )

        self.assertTrue(
            backend.save_news_data(
                NewsData(date="2026-07-24", crawl_time="09-00", items={})
            )
        )
        self.assertTrue(
            backend.save_rss_data(
                RSSData(date="2026-07-24", crawl_time="09-00", items={})
            )
        )

    def test_remote_abort_resets_batch_state_without_uploading(self):
        backend = self._backend()
        backend._batch_mode = True
        backend._batch_dirty = {("2026-07-24", "news")}
        backend._sqlite_batch_active = True
        backend._sqlite_batch_connections = {}

        result = backend.abort_batch()

        self.assertFalse(result.committed)
        self.assertTrue(result.rolled_back)
        self.assertFalse(backend._batch_mode)
        self.assertEqual(backend._batch_dirty, set())
        self.assertFalse(backend._sqlite_batch_active)


class RemoteStorageBatchTests(unittest.TestCase):
    date = "2026-07-24"

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.s3 = VersionedFakeS3()
        patcher = patch(
            "trendradar.storage.remote.boto3.client",
            return_value=self.s3,
        )
        patcher.start()
        self.addCleanup(patcher.stop)
        self.backend = RemoteStorageBackend(
            bucket_name="bucket",
            access_key_id="key",
            secret_access_key="secret",
            endpoint_url="https://s3.example.test",
            temp_dir=self.temp_dir.name,
        )
        self.addCleanup(self.backend.cleanup)

    def _news(self, title):
        return NewsData(
            date=self.date,
            crawl_time="09-00",
            items={
                "source": [
                    NewsItem(
                        title=title,
                        source_id="source",
                        rank=1,
                        url=f"https://example.com/{title}",
                    )
                ]
            },
            id_to_name={"source": "Source"},
        )

    def test_normal_batch_uploads_each_database_once(self):
        with self.backend.batch() as batch:
            self.backend.save_ai_filter_tags(
                [{"tag": "first"}],
                1,
                "hash",
                date=self.date,
            )
            self.backend.save_ai_filter_tags(
                [{"tag": "second"}],
                1,
                "hash",
                date=self.date,
            )

        self.assertTrue(batch.result.committed)
        self.assertEqual(len(self.s3.put_calls), 1)

    def test_user_exception_rolls_back_and_uploads_nothing(self):
        with self.assertRaisesRegex(RuntimeError, "injected"):
            with self.backend.batch():
                self.backend.save_ai_filter_tags(
                    [{"tag": "discarded"}],
                    1,
                    "hash",
                    date=self.date,
                )
                raise RuntimeError("injected")

        self.assertEqual(self.s3.put_calls, [])
        self.assertEqual(self.backend.get_active_ai_filter_tags(self.date), [])

    def test_upload_failure_is_explicit_in_batch_result(self):
        self.s3.put_error = "500"
        with self.backend.batch() as batch:
            self.backend.save_ai_filter_tags(
                [{"tag": "local-only"}],
                1,
                "hash",
                date=self.date,
            )

        self.assertFalse(batch.result.committed)
        self.assertEqual(len(batch.result.databases), 1)
        self.assertTrue(batch.result.databases[0].committed)
        self.assertFalse(batch.result.databases[0].uploaded)
        self.assertIn("PUT", batch.result.databases[0].error)

    def test_batch_conflict_replays_complete_command_log(self):
        other = RemoteStorageBackend(
            bucket_name="bucket",
            access_key_id="key",
            secret_access_key="secret",
            endpoint_url="https://s3.example.test",
            temp_dir=self.temp_dir.name,
        )
        self.addCleanup(other.cleanup)

        with self.backend.batch() as batch:
            self.backend.save_ai_filter_tags(
                [{"tag": "batch-tag"}],
                1,
                "hash",
                date=self.date,
            )
            self.assertTrue(other.save_news_data(self._news("concurrent-news")))

        self.assertTrue(batch.result.committed)
        content, _etag = self.s3.objects["news/2026-07-24.db"]
        path = Path(self.temp_dir.name) / "batch-final.db"
        path.write_bytes(content)
        connection = sqlite3.connect(path)
        self.assertEqual(
            connection.execute("SELECT title FROM news_items").fetchall(),
            [("concurrent-news",)],
        )
        self.assertEqual(
            connection.execute("SELECT tag FROM ai_filter_tags").fetchall(),
            [("batch-tag",)],
        )
        connection.close()

    def test_cross_database_partial_upload_is_reported_per_database(self):
        original_put = self.s3.put_object

        def fail_rss(**kwargs):
            if kwargs["Key"].startswith("rss/"):
                self.s3.put_calls.append(kwargs.copy())
                raise client_error("500", "PutObject")
            return original_put(**kwargs)

        self.s3.put_object = fail_rss
        with self.backend.batch() as batch:
            self.backend.save_news_data(self._news("news-kept"))
            self.backend.save_rss_data(
                RSSData(
                    date=self.date,
                    crawl_time="09-00",
                    items={
                        "feed": [
                            RSSItem(
                                title="rss-local-only",
                                feed_id="feed",
                                url="https://example.com/rss",
                            )
                        ]
                    },
                    id_to_name={"feed": "Feed"},
                )
            )

        outcomes = {
            item.database: item
            for item in batch.result.databases
        }
        self.assertFalse(batch.result.committed)
        self.assertTrue(outcomes[f"news:{self.date}"].uploaded)
        self.assertFalse(outcomes[f"rss:{self.date}"].uploaded)
        self.assertIn("PUT", outcomes[f"rss:{self.date}"].error)


if __name__ == "__main__":
    unittest.main()
