import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from botocore.exceptions import ClientError

from trendradar.storage.errors import RemoteDataError, RemoteDependencyError
from trendradar.storage.remote import RemoteStorageBackend


def client_error(code, operation="HeadObject"):
    return ClientError(
        {"Error": {"Code": str(code), "Message": "injected"}},
        operation,
    )


class FakeBody:
    def __init__(self, chunks):
        self.chunks = chunks

    def iter_chunks(self, chunk_size):
        del chunk_size
        yield from self.chunks


class FakeS3:
    def __init__(self):
        self.head_result = {}
        self.head_error = None
        self.get_result = None
        self.get_error = None

    def head_object(self, **kwargs):
        del kwargs
        if self.head_error:
            raise self.head_error
        return self.head_result

    def get_object(self, **kwargs):
        del kwargs
        if self.get_error:
            raise self.get_error
        return self.get_result


class RemoteStorageSafetyTests(unittest.TestCase):
    date = "2026-07-24"

    def setUp(self):
        self.parent_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.parent_dir.cleanup)
        self.fake_s3 = FakeS3()
        client_patcher = patch(
            "trendradar.storage.remote.boto3.client",
            return_value=self.fake_s3,
        )
        client_patcher.start()
        self.addCleanup(client_patcher.stop)
        self.backend = RemoteStorageBackend(
            bucket_name="bucket",
            access_key_id="key",
            secret_access_key="secret",
            endpoint_url="https://s3.example.test",
            temp_dir=self.parent_dir.name,
        )
        self.addCleanup(self.backend.cleanup)

    def _valid_sqlite_bytes(self):
        database_path = Path(self.parent_dir.name) / "valid-source.db"
        connection = sqlite3.connect(database_path)
        connection.execute("CREATE TABLE sample (value TEXT)")
        connection.commit()
        connection.close()
        return database_path.read_bytes()

    def test_caller_temp_directory_is_only_a_parent(self):
        parent = Path(self.parent_dir.name)
        sentinel = parent / "sentinel.txt"
        sentinel.write_text("keep", encoding="utf-8")
        owned_dir = self.backend.temp_dir

        self.assertEqual(owned_dir.parent, parent)
        self.assertNotEqual(owned_dir, parent)
        self.backend.cleanup()

        self.assertTrue(sentinel.exists())
        self.assertFalse(owned_dir.exists())

    def test_head_only_maps_explicit_not_found_to_false(self):
        for code in ("404", "NoSuchKey", "Not Found"):
            with self.subTest(code=code):
                self.fake_s3.head_error = client_error(code)
                self.assertFalse(self.backend._check_object_exists("news/date.db"))

    def test_head_dependency_errors_are_not_mapped_to_missing(self):
        for code in ("403", "500", "SlowDown"):
            with self.subTest(code=code):
                self.fake_s3.head_error = client_error(code)
                with self.assertRaises(RemoteDependencyError):
                    self.backend._check_object_exists("news/date.db")

        self.fake_s3.head_error = TimeoutError("injected timeout")
        with self.assertRaises(RemoteDependencyError):
            self.backend._check_object_exists("news/date.db")

    def test_dependency_failure_does_not_create_empty_database(self):
        self.fake_s3.head_error = client_error("403")
        local_path = self.backend._get_local_db_path(self.date)

        with self.assertRaises(RemoteDependencyError):
            self.backend._get_connection(self.date)

        self.assertFalse(local_path.exists())

    def test_partial_download_keeps_previous_database_and_removes_part(self):
        local_path = self.backend._get_local_db_path(self.date)
        local_path.write_bytes(b"previous-complete-database")
        self.fake_s3.head_result = {"ContentLength": 100, "ETag": '"v1"'}
        self.fake_s3.get_result = {
            "ContentLength": 100,
            "Body": FakeBody([b"partial"]),
        }

        with self.assertRaises(RemoteDataError):
            self.backend._download_sqlite(self.date)

        self.assertEqual(local_path.read_bytes(), b"previous-complete-database")
        self.assertFalse(local_path.with_suffix(".db.part").exists())

    def test_corrupt_sqlite_keeps_previous_database(self):
        local_path = self.backend._get_local_db_path(self.date)
        local_path.write_bytes(b"previous-complete-database")
        corrupt = b"not a sqlite database"
        self.fake_s3.head_result = {
            "ContentLength": len(corrupt),
            "ETag": '"v1"',
        }
        self.fake_s3.get_result = {
            "ContentLength": len(corrupt),
            "Body": FakeBody([corrupt]),
        }

        with self.assertRaises(RemoteDataError):
            self.backend._download_sqlite(self.date)

        self.assertEqual(local_path.read_bytes(), b"previous-complete-database")

    def test_valid_download_atomically_replaces_previous_database(self):
        local_path = self.backend._get_local_db_path(self.date)
        local_path.write_bytes(b"previous-complete-database")
        database = self._valid_sqlite_bytes()
        self.fake_s3.head_result = {
            "ContentLength": len(database),
            "ETag": '"v1"',
        }
        self.fake_s3.get_result = {
            "ContentLength": len(database),
            "Body": FakeBody([database[:17], database[17:]]),
        }

        downloaded = self.backend._download_sqlite(self.date)

        self.assertEqual(downloaded, local_path)
        self.assertEqual(local_path.read_bytes(), database)
        self.assertFalse(local_path.with_suffix(".db.part").exists())


if __name__ == "__main__":
    unittest.main()
