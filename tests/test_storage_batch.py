import tempfile
import unittest

from trendradar.storage.local import LocalStorageBackend


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


if __name__ == "__main__":
    unittest.main()
