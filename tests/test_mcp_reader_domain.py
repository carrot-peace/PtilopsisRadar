import ast
import asyncio
import hashlib
import json
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from fastmcp import Client

from mcp_server.context import MCPContext
from mcp_server.server import create_server, mcp
from mcp_server.tools.article_reader import ArticleReaderTools


ROOT = Path(__file__).parents[1]
READER_HANDLERS = {"read_article", "read_articles_batch"}
EXPECTED_DESCRIPTION_DIGEST = (
    "256f3a61894b2e899e2890dc1c83b0050893c9f8db07289baa0f25d6060404f9"
)


class ReaderFeatureBoundaryTests(unittest.TestCase):
    def test_server_delegates_reader_handlers(self):
        server_tree = ast.parse(
            (ROOT / "mcp_server/server.py").read_text(encoding="utf-8")
        )
        defined_functions = {
            node.name
            for node in ast.walk(server_tree)
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        }

        self.assertTrue(READER_HANDLERS.isdisjoint(defined_functions))

    def test_public_parameter_guidance_is_stable(self):
        tools = asyncio.run(mcp.get_tools())
        descriptions = {
            name: tools[name].description
            for name in sorted(READER_HANDLERS)
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


class ReaderFeatureDelegationTests(unittest.IsolatedAsyncioTestCase):
    async def test_handlers_use_reader_dependency_and_bound_timeout(self):
        article = Mock()
        article.read_article.return_value = {"success": True}
        article.read_articles_batch.return_value = {"success": True}
        context = MCPContext.from_tools(
            project_root="/tmp/project",
            tools={"article": article},
        )

        async with Client(create_server(context=context)) as client:
            single = await client.call_tool(
                "read_article",
                {"url": "https://example.com", "timeout": 1},
            )
            batch = await client.call_tool(
                "read_articles_batch",
                {
                    "urls": ["https://example.com/a"],
                    "timeout": 90,
                },
            )

        self.assertTrue(json.loads(single.content[0].text)["success"])
        self.assertTrue(json.loads(batch.content[0].text)["success"])
        article.read_article.assert_called_once_with(
            url="https://example.com",
            timeout=10,
        )
        article.read_articles_batch.assert_called_once_with(
            urls=["https://example.com/a"],
            timeout=60,
        )


class ArticleReaderSafetyTests(unittest.TestCase):
    def setUp(self):
        self.tools = ArticleReaderTools()
        self.tools._throttle = Mock()

    @patch("mcp_server.tools.article_reader.requests.get")
    def test_direct_reader_enforces_timeout_bounds(self, get):
        get.return_value = SimpleNamespace(
            status_code=200,
            text="# Article",
        )

        result = self.tools.read_article(
            "https://example.com",
            timeout=1,
        )

        self.assertTrue(result["success"])
        self.assertEqual(get.call_args.kwargs["timeout"], 10)

    @patch("mcp_server.tools.article_reader.requests.get")
    def test_unexpected_request_error_does_not_leak_details(self, get):
        get.side_effect = RuntimeError("secret request internals")

        result = self.tools.read_article("https://example.com")
        encoded = json.dumps(result, ensure_ascii=False)

        self.assertFalse(result["success"])
        self.assertEqual(result["error"]["code"], "REQUEST_ERROR")
        self.assertNotIn("secret request internals", encoded)

    def test_batch_rejects_string_instead_of_iterating_characters(self):
        result = self.tools.read_articles_batch(
            "https://example.com",
        )

        self.assertFalse(result["success"])
        self.assertEqual(
            result["error"]["code"],
            "INVALID_PARAMETER",
        )

    def test_throttle_has_one_lock_per_reader_context(self):
        first = ArticleReaderTools()
        second = ArticleReaderTools()

        self.assertIsNot(first._throttle_lock, second._throttle_lock)


if __name__ == "__main__":
    unittest.main()
