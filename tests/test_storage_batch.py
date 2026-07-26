import sqlite3
import tempfile
import unittest

from trendradar.ai.filter import AIFilterResult
from trendradar.context import AppContext
from trendradar.storage.base import NewsData, RSSData
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


if __name__ == "__main__":
    unittest.main()
