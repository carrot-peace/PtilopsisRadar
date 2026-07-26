import sqlite3
import unittest
from dataclasses import FrozenInstanceError

from trendradar.storage.results import ItemFailure, WriteResult
from trendradar.storage.unit_of_work import SQLiteUnitOfWork


class WriteResultTests(unittest.TestCase):
    def test_result_is_immutable_and_keeps_structured_failure(self):
        failure = ItemFailure(
            identity="09-00",
            operation="save_news_data",
            error_code="IntegrityError",
            message="injected failure",
        )
        result = WriteResult(committed=False, failures=(failure,))

        self.assertEqual(result.failures, (failure,))
        with self.assertRaises(FrozenInstanceError):
            result.committed = True


class SQLiteUnitOfWorkTests(unittest.TestCase):
    def setUp(self):
        self.connection = sqlite3.connect(":memory:")
        self.addCleanup(self.connection.close)
        self.connection.execute("CREATE TABLE records (value TEXT)")
        self.connection.commit()

    def test_commits_successful_block(self):
        with SQLiteUnitOfWork(self.connection) as cursor:
            cursor.execute("INSERT INTO records VALUES ('kept')")

        self.assertEqual(
            self.connection.execute("SELECT value FROM records").fetchall(),
            [("kept",)],
        )

    def test_rolls_back_failed_block_and_releases_connection(self):
        with self.assertRaisesRegex(RuntimeError, "injected"):
            with SQLiteUnitOfWork(self.connection) as cursor:
                cursor.execute("INSERT INTO records VALUES ('discarded')")
                raise RuntimeError("injected")

        self.assertEqual(
            self.connection.execute("SELECT value FROM records").fetchall(),
            [],
        )
        with SQLiteUnitOfWork(self.connection) as cursor:
            cursor.execute("INSERT INTO records VALUES ('recovered')")
        self.assertEqual(
            self.connection.execute("SELECT value FROM records").fetchall(),
            [("recovered",)],
        )


if __name__ == "__main__":
    unittest.main()
