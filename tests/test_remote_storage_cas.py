import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from botocore.exceptions import ClientError

from trendradar.storage.base import NewsData, NewsItem
from trendradar.storage.remote import RemoteStorageBackend


def client_error(code, operation):
    return ClientError(
        {"Error": {"Code": str(code), "Message": "injected"}},
        operation,
    )


class FakeBody:
    def __init__(self, content):
        self.content = content

    def iter_chunks(self, chunk_size):
        for offset in range(0, len(self.content), chunk_size):
            yield self.content[offset:offset + chunk_size]


class VersionedFakeS3:
    def __init__(self):
        self.objects = {}
        self.version = 0
        self.put_calls = []
        self.forced_conflicts = 0
        self.reject_conditions = False
        self.put_error = None
        self.omit_put_etag = False

    def seed(self, key, content, etag='"v1"'):
        self.objects[key] = (content, etag)
        self.version = max(self.version, 1)

    def head_object(self, Bucket, Key):
        del Bucket
        if Key not in self.objects:
            raise client_error("404", "HeadObject")
        content, etag = self.objects[Key]
        return {"ContentLength": len(content), "ETag": etag}

    def get_object(self, Bucket, Key):
        del Bucket
        if Key not in self.objects:
            raise client_error("NoSuchKey", "GetObject")
        content, etag = self.objects[Key]
        return {
            "ContentLength": len(content),
            "ETag": etag,
            "Body": FakeBody(content),
        }

    def put_object(self, **kwargs):
        self.put_calls.append(kwargs.copy())
        if self.put_error:
            raise client_error(self.put_error, "PutObject")
        if self.reject_conditions and (
            "IfMatch" in kwargs or "IfNoneMatch" in kwargs
        ):
            raise client_error("NotImplemented", "PutObject")
        if self.forced_conflicts:
            self.forced_conflicts -= 1
            raise client_error("PreconditionFailed", "PutObject")

        key = kwargs["Key"]
        current = self.objects.get(key)
        if kwargs.get("IfNoneMatch") == "*" and current is not None:
            raise client_error("PreconditionFailed", "PutObject")
        if "IfMatch" in kwargs:
            if current is None or current[1] != kwargs["IfMatch"]:
                raise client_error("PreconditionFailed", "PutObject")

        self.version += 1
        etag = f'"v{self.version}"'
        self.objects[key] = (kwargs["Body"], etag)
        return {} if self.omit_put_etag else {"ETag": etag}


class RemoteStorageCASTests(unittest.TestCase):
    date = "2026-07-24"
    key = "news/2026-07-24.db"

    def setUp(self):
        self.parent_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.parent_dir.cleanup)
        self.s3 = VersionedFakeS3()
        client_patcher = patch(
            "trendradar.storage.remote.boto3.client",
            return_value=self.s3,
        )
        client_patcher.start()
        self.addCleanup(client_patcher.stop)
        self.backends = []

    def _backend(self, **kwargs):
        backend = RemoteStorageBackend(
            bucket_name="bucket",
            access_key_id="key",
            secret_access_key="secret",
            endpoint_url="https://s3.example.test",
            temp_dir=self.parent_dir.name,
            **kwargs,
        )
        self.backends.append(backend)
        self.addCleanup(backend.cleanup)
        return backend

    def _empty_database(self):
        path = Path(self.parent_dir.name) / "seed.db"
        connection = sqlite3.connect(path)
        storage_dir = Path(__file__).parents[1] / "trendradar" / "storage"
        connection.executescript(
            (storage_dir / "schema.sql").read_text(encoding="utf-8")
        )
        connection.executescript(
            (storage_dir / "ai_filter_schema.sql").read_text(encoding="utf-8")
        )
        connection.commit()
        connection.close()
        return path.read_bytes()

    def _news(self, title):
        return NewsData(
            date=self.date,
            crawl_time=f"09-{len(title):02d}",
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

    def test_first_create_uses_if_none_match_and_saves_new_version(self):
        backend = self._backend()

        self.assertTrue(backend.save_news_data(self._news("first")))

        self.assertEqual(self.s3.put_calls[0]["IfNoneMatch"], "*")
        self.assertNotIn("IfMatch", self.s3.put_calls[0])
        self.assertEqual(backend._remote_versions[(self.date, "news")], '"v1"')

    def test_two_writers_replay_after_conflict_without_lost_update(self):
        self.s3.seed(self.key, self._empty_database())
        first = self._backend()
        second = self._backend()
        first._get_connection(self.date)
        second._get_connection(self.date)

        self.assertTrue(first.save_news_data(self._news("alpha")))
        self.assertTrue(second.save_news_data(self._news("beta")))

        content, _etag = self.s3.objects[self.key]
        final_path = Path(self.parent_dir.name) / "final.db"
        final_path.write_bytes(content)
        connection = sqlite3.connect(final_path)
        titles = {
            row[0]
            for row in connection.execute("SELECT title FROM news_items")
        }
        connection.close()
        self.assertEqual(titles, {"alpha", "beta"})
        self.assertGreaterEqual(len(self.s3.put_calls), 3)

    def test_three_conflicts_fail_and_keep_diagnostic_state(self):
        self.s3.seed(self.key, self._empty_database())
        self.s3.forced_conflicts = 3
        backend = self._backend()

        self.assertFalse(backend.save_news_data(self._news("never-written")))

        self.assertEqual(len(self.s3.put_calls), 3)
        self.assertIn("conflict", backend.last_upload_error.lower())

    def test_provider_without_conditions_fails_closed_by_default(self):
        self.s3.reject_conditions = True
        backend = self._backend()

        self.assertFalse(backend.save_news_data(self._news("closed")))

        self.assertIn("conditional", backend.last_upload_error.lower())
        self.assertNotIn(self.key, self.s3.objects)

    def test_explicit_single_writer_allows_unconditional_upload(self):
        self.s3.reject_conditions = True
        backend = self._backend(single_writer=True)

        self.assertTrue(backend.save_news_data(self._news("compatible")))

        self.assertNotIn("IfMatch", self.s3.put_calls[0])
        self.assertNotIn("IfNoneMatch", self.s3.put_calls[0])

    def test_put_failure_is_not_reported_as_success(self):
        self.s3.put_error = "500"
        backend = self._backend()

        self.assertFalse(backend.save_news_data(self._news("failed")))

        self.assertIn("put", backend.last_upload_error.lower())

    def test_multi_writer_put_without_etag_fails_closed(self):
        self.s3.omit_put_etag = True
        backend = self._backend()

        self.assertFalse(backend.save_news_data(self._news("unbound-version")))

        self.assertIn("no remote version", backend.last_upload_error.lower())
        self.assertNotIn((self.date, "news"), backend._remote_versions)


if __name__ == "__main__":
    unittest.main()
