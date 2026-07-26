import unittest


class StorageRepositoryBoundaryTests(unittest.TestCase):
    def test_backend_is_partitioned_into_repository_protocols(self):
        from trendradar.storage.local import LocalStorageBackend
        from trendradar.storage.repositories import (
            AIFilterRepository,
            NewsRepository,
            RSSRepository,
            ScheduleRepository,
            StorageRepositories,
        )

        backend = LocalStorageBackend(data_dir="output")
        repositories = StorageRepositories.from_backend(backend)

        self.assertIs(repositories.news, backend)
        self.assertIs(repositories.rss, backend)
        self.assertIs(repositories.schedule, backend)
        self.assertIs(repositories.ai_filter, backend)
        self.assertIsInstance(backend, NewsRepository)
        self.assertIsInstance(backend, RSSRepository)
        self.assertIsInstance(backend, ScheduleRepository)
        self.assertIsInstance(backend, AIFilterRepository)

    def test_sqlite_composite_does_not_own_domain_repository_methods(self):
        from trendradar.storage.sqlite_mixin import SQLiteStorageMixin

        self.assertNotIn("_save_news_data_impl", SQLiteStorageMixin.__dict__)
        self.assertNotIn("_save_rss_data_impl", SQLiteStorageMixin.__dict__)
        self.assertNotIn("_record_period_execution_impl", SQLiteStorageMixin.__dict__)
        self.assertNotIn("_save_tags_impl", SQLiteStorageMixin.__dict__)
        repository_bases = {
            base.__name__ for base in SQLiteStorageMixin.__mro__
        }
        self.assertTrue(
            {
                "SQLiteNewsRepositoryMixin",
                "SQLiteRSSRepositoryMixin",
                "SQLiteScheduleRepositoryMixin",
                "SQLiteAIFilterRepositoryMixin",
            }.issubset(repository_bases)
        )

if __name__ == "__main__":
    unittest.main()
