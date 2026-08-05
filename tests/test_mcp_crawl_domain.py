import ast
import asyncio
import hashlib
import json
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import Mock, patch

from fastmcp import Client

from mcp_server.context import MCPContext
from mcp_server.server import create_server, mcp
from mcp_server.tools.crawl import CrawlTools


ROOT = Path(__file__).parents[1]
EXPECTED_DESCRIPTION_DIGEST = (
    "2348b284b5b73da542e2ec95a0108a455ffcf8e44df3a24701280ff884dde446"
)


class CrawlFeatureBoundaryTests(unittest.TestCase):
    def test_server_delegates_crawl_handler(self):
        server_tree = ast.parse(
            (ROOT / "mcp_server/server.py").read_text(encoding="utf-8")
        )
        defined_functions = {
            node.name
            for node in ast.walk(server_tree)
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        }

        self.assertNotIn("trigger_crawl", defined_functions)

    def test_public_parameter_guidance_is_stable(self):
        tools = asyncio.run(mcp.get_tools())
        encoded = json.dumps(
            {"trigger_crawl": tools["trigger_crawl"].description},
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
        ).encode()

        self.assertEqual(
            hashlib.sha256(encoded).hexdigest(),
            EXPECTED_DESCRIPTION_DIGEST,
        )


class CrawlFeatureDelegationTests(unittest.IsolatedAsyncioTestCase):
    async def test_handler_uses_crawl_dependency(self):
        crawl = Mock()
        crawl.trigger_crawl.return_value = {
            "success": True,
            "summary": {"saved_to_local": False},
        }
        context = MCPContext.from_tools(
            project_root="/tmp/project",
            tools={"crawl": crawl},
        )

        async with Client(create_server(context=context)) as client:
            result = await client.call_tool(
                "trigger_crawl",
                {
                    "platforms": ["weibo"],
                    "save_to_local": False,
                    "include_url": True,
                },
            )

        self.assertTrue(json.loads(result.content[0].text)["success"])
        crawl.trigger_crawl.assert_called_once_with(
            platforms=["weibo"],
            save_to_local=False,
            include_url=True,
        )


class CrawlPersistenceTests(unittest.TestCase):
    def setUp(self):
        self.tools = CrawlTools("/tmp/project")
        self.platform = {"id": "weibo", "name": "微博"}
        self.config = {
            "app": {"timezone": "Asia/Shanghai"},
            "platforms": {"sources": [self.platform]},
            "advanced": {"crawler": {}},
        }
        self.crawl_result = (
            {
                "weibo": {
                    "示例新闻": {
                        "ranks": [1],
                        "url": "https://example.com",
                        "mobileUrl": "",
                    }
                }
            },
            {"weibo": "微博"},
            [],
        )

    def test_save_disabled_never_constructs_or_writes_local_storage(self):
        self.tools._load_crawl_config = Mock(
            return_value=(self.config, [self.platform])
        )
        now = datetime(2026, 7, 26, 12, 0, 0)

        with patch(
            "trendradar.crawler.fetcher.DataFetcher"
        ) as fetcher_class, patch(
            "trendradar.storage.local.LocalStorageBackend"
        ) as storage_class, patch(
            "trendradar.storage.base.convert_crawl_results_to_news_data"
        ) as convert, patch(
            "trendradar.utils.time.get_configured_time",
            return_value=now,
        ), patch(
            "trendradar.utils.time.format_date_folder",
            return_value="2026-07-26",
        ), patch(
            "trendradar.utils.time.format_time_filename",
            return_value="12-00",
        ):
            fetcher_class.return_value.crawl_websites.return_value = (
                self.crawl_result
            )

            result = self.tools.trigger_crawl(save_to_local=False)

        self.assertTrue(result["success"])
        self.assertFalse(result["summary"]["saved_to_local"])
        self.assertNotIn("save_error", result)
        self.assertIn("未持久化", result["note"])
        storage_class.assert_not_called()
        convert.assert_not_called()

    def test_save_enabled_persists_database_and_reports(self):
        storage = Mock()
        storage.save_news_data.return_value = True
        storage.save_txt_snapshot.return_value = "/tmp/news.txt"
        storage.save_html_report.return_value = "/tmp/news.html"
        now = datetime(2026, 7, 26, 12, 0, 0)
        results, id_to_name, failed_ids = self.crawl_result

        success, error, files = self.tools._persist_crawl_data(
            storage,
            {"news": "data"},
            True,
            results,
            id_to_name,
            failed_ids,
            now,
            "12-00",
        )

        self.assertTrue(success)
        self.assertEqual(error, "")
        self.assertEqual(
            files,
            {"txt": "/tmp/news.txt", "html": "/tmp/news.html"},
        )
        storage.save_news_data.assert_called_once_with({"news": "data"})
        storage.save_txt_snapshot.assert_called_once_with({"news": "data"})
        storage.save_html_report.assert_called_once()

    def test_unexpected_error_does_not_leak_details(self):
        self.tools._load_crawl_config = Mock(
            side_effect=RuntimeError("secret implementation detail")
        )

        result = self.tools.trigger_crawl()
        encoded = json.dumps(result, ensure_ascii=False)

        self.assertFalse(result["success"])
        self.assertEqual(result["error"]["code"], "INTERNAL_ERROR")
        self.assertNotIn("traceback", encoded.lower())
        self.assertNotIn("secret implementation detail", encoded)


if __name__ == "__main__":
    unittest.main()
