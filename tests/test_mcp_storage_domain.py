import ast
import asyncio
import hashlib
import json
import sqlite3
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import Mock, patch

from fastmcp import Client

from mcp_server.context import MCPContext
from mcp_server.server import create_server, mcp
from mcp_server.tools.storage_sync import StorageSyncTools


ROOT = Path(__file__).parents[1]
STORAGE_HANDLERS = {
    "sync_from_remote",
    "get_storage_status",
    "list_available_dates",
}
EXPECTED_DESCRIPTION_DIGEST = (
    "e2b56047080a464bf32899b2810fb3a4c78161cbb14b4175a6bc82e88269389b"
)


class StorageFeatureBoundaryTests(unittest.TestCase):
    def test_server_delegates_storage_handlers(self):
        server_tree = ast.parse(
            (ROOT / "mcp_server/server.py").read_text(encoding="utf-8")
        )
        defined_functions = {
            node.name
            for node in ast.walk(server_tree)
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        }

        self.assertTrue(STORAGE_HANDLERS.isdisjoint(defined_functions))

    def test_public_parameter_guidance_is_stable(self):
        tools = asyncio.run(mcp.get_tools())
        descriptions = {
            name: tools[name].description
            for name in sorted(STORAGE_HANDLERS)
        }
        encoded = json.dumps(
            descriptions,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
        ).encode()

        self.assertEqual(
            hashlib.sha256(encoded).hexdigest(),
            EXPECTED_DESCRIPTION_DIGEST,
        )


class StorageFeatureDelegationTests(unittest.IsolatedAsyncioTestCase):
    async def test_handlers_use_storage_dependency(self):
        storage = Mock()
        storage.sync_from_remote.return_value = {"success": True}
        storage.get_storage_status.return_value = {"success": True}
        storage.list_available_dates.return_value = {"success": True}
        context = MCPContext.from_tools(
            project_root="/tmp/project",
            tools={"storage": storage},
        )

        async with Client(create_server(context=context)) as client:
            sync = await client.call_tool(
                "sync_from_remote",
                {"days": 30},
            )
            status = await client.call_tool("get_storage_status", {})
            dates = await client.call_tool(
                "list_available_dates",
                {"source": "local"},
            )

        self.assertTrue(json.loads(sync.content[0].text)["success"])
        self.assertTrue(json.loads(status.content[0].text)["success"])
        self.assertTrue(json.loads(dates.content[0].text)["success"])
        storage.sync_from_remote.assert_called_once_with(days=30)
        storage.get_storage_status.assert_called_once_with()
        storage.list_available_dates.assert_called_once_with(
            source="local"
        )


class StoragePullContractTests(unittest.TestCase):
    def test_sync_targets_query_compatible_news_path(self):
        with tempfile.TemporaryDirectory() as tmp:
            tools = StorageSyncTools(tmp)
            backend = Mock()
            backend.list_remote_dates.return_value = ["2026-07-26"]
            tools._has_remote_config = Mock(return_value=True)
            tools._get_remote_backend = Mock(return_value=backend)
            tools._load_config = Mock(
                return_value={
                    "app": {"timezone": "Asia/Shanghai"},
                    "storage": {
                        "local": {"data_dir": "output"}
                    },
                }
            )
            tools._get_local_dates = Mock(return_value=[])
            expected = (
                Path(tmp) / "output" / "news" / "2026-07-26.db"
            )

            def write_database(*, date, db_type, local_path):
                self.assertEqual(date, "2026-07-26")
                self.assertEqual(db_type, "news")
                local_path.parent.mkdir(parents=True)
                connection = sqlite3.connect(local_path)
                connection.execute("CREATE TABLE sample (value TEXT)")
                connection.commit()
                connection.close()
                return local_path

            backend.download_database.side_effect = write_database

            with patch(
                "trendradar.utils.time.get_configured_time",
                return_value=datetime(2026, 7, 26, 12),
            ):
                result = tools.sync_from_remote(days=1)
            from trendradar.storage.query import SQLiteQueryRepository

            available_dates = SQLiteQueryRepository(
                Path(tmp) / "output"
            ).available_dates()

        self.assertTrue(result["success"])
        self.assertEqual(
            result["data"]["synced_dates"],
            ["2026-07-26"],
        )
        self.assertEqual(available_dates, ["2026-07-26"])
        backend.download_database.assert_called_once_with(
            date="2026-07-26",
            db_type="news",
            local_path=expected,
        )
        self.assertFalse(
            backend.s3_client.download_file.called
        )

    def test_zero_days_is_noop_without_remote_configuration(self):
        tools = StorageSyncTools("/tmp/project")
        tools._has_remote_config = Mock(return_value=False)

        result = tools.sync_from_remote(days=0)

        self.assertTrue(result["success"])
        self.assertEqual(result["summary"]["synced_files"], 0)
        tools._has_remote_config.assert_not_called()

    def test_pull_days_has_explicit_upper_bound(self):
        tools = StorageSyncTools("/tmp/project")

        result = tools.sync_from_remote(days=366)

        self.assertFalse(result["success"])
        self.assertEqual(
            result["error"]["code"],
            "INVALID_PARAMETER",
        )


if __name__ == "__main__":
    unittest.main()
