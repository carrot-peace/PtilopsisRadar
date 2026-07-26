import os
import unittest
from unittest.mock import Mock, patch

from trendradar.context import AppContext
from trendradar.core.loader import _load_storage_config
from trendradar.storage.manager import StorageManager

class RemoteSingleWriterConfigTests(unittest.TestCase):
    def test_loader_reads_yaml_and_environment_override(self):
        loaded = _load_storage_config(
            {"storage": {"remote": {"single_writer": True}}}
        )
        self.assertTrue(loaded["REMOTE"]["SINGLE_WRITER"])

        with patch.dict(os.environ, {"S3_SINGLE_WRITER": "false"}):
            overridden = _load_storage_config(
                {"storage": {"remote": {"single_writer": True}}}
            )
        self.assertFalse(overridden["REMOTE"]["SINGLE_WRITER"])

    def test_context_forwards_single_writer_to_storage_manager(self):
        factory = Mock()
        context = AppContext(
            {
                "STORAGE": {
                    "REMOTE": {"SINGLE_WRITER": True},
                    "FORMATS": {},
                    "LOCAL": {},
                    "PULL": {},
                }
            },
            storage_factory=factory,
        )
        context.get_storage_manager()

        self.assertTrue(
            factory.call_args.kwargs["remote_config"]["single_writer"]
        )

    def test_manager_uses_environment_fallback_for_direct_construction(self):
        manager = StorageManager(
            remote_config={
                "bucket_name": "bucket",
                "access_key_id": "key",
                "secret_access_key": "secret",
                "endpoint_url": "https://s3.example.test",
            }
        )

        with (
            patch.dict(os.environ, {"S3_SINGLE_WRITER": "true"}),
            patch(
                "trendradar.storage.remote.RemoteStorageBackend"
            ) as backend_class,
        ):
            manager._create_remote_backend()

        self.assertTrue(
            backend_class.call_args.kwargs["single_writer"]
        )


if __name__ == "__main__":
    unittest.main()
