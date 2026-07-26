import asyncio
import ast
import hashlib
import json
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from fastmcp import Client
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from mcp_server.context import MCPContext
from mcp_server.server import create_server, mcp, run_server
from mcp_server.services.cache_service import CacheService
from mcp_server.services.data_service import DataService
from mcp_server.services.parser_service import ParserService


EXPECTED_TOOLS = {
    "resolve_date_range",
    "get_latest_news",
    "get_trending_topics",
    "get_latest_rss",
    "search_rss",
    "get_rss_feeds_status",
    "get_news_by_date",
    "analyze_topic_trend",
    "analyze_data_insights",
    "analyze_sentiment",
    "find_related_news",
    "generate_summary_report",
    "aggregate_news",
    "compare_periods",
    "search_news",
    "get_current_config",
    "get_system_status",
    "check_version",
    "trigger_crawl",
    "sync_from_remote",
    "get_storage_status",
    "list_available_dates",
    "read_article",
    "read_articles_batch",
}

EXPECTED_RESOURCES = {
    "config://platforms",
    "config://rss-feeds",
    "data://available-dates",
    "config://keywords",
}

EXPECTED_TOOL_SCHEMA_DIGEST = (
    "4ccef9a9080c7a883f856ac08ce6a02e6d16614169776facc9859b2ce3430d1b"
)


class MCPRegistrationContractTests(unittest.TestCase):
    def test_tool_names_are_stable(self):
        tools = asyncio.run(mcp.get_tools())

        self.assertEqual(set(tools), EXPECTED_TOOLS)

    def test_resource_uris_are_stable(self):
        resources = asyncio.run(mcp.get_resources())

        self.assertEqual(set(resources), EXPECTED_RESOURCES)

    def test_tool_input_schemas_are_stable(self):
        tools = asyncio.run(mcp.get_tools())
        schemas = {
            name: tools[name].parameters
            for name in sorted(tools)
        }
        encoded = json.dumps(
            schemas,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
        ).encode()

        self.assertEqual(
            hashlib.sha256(encoded).hexdigest(),
            EXPECTED_TOOL_SCHEMA_DIGEST,
        )


class MCPApplicationFactoryTests(unittest.TestCase):
    def test_context_factory_builds_independent_tool_sets(self):
        tool_names = {
            "DataQueryTools": "data",
            "AnalyticsTools": "analytics",
            "SearchTools": "search",
            "ConfigManagementTools": "config",
            "SystemManagementTools": "system",
            "StorageSyncTools": "storage",
            "ArticleReaderTools": "article",
        }
        patches = {
            class_name: patch(
                f"mcp_server.context.{class_name}",
                side_effect=lambda root, name=name: (name, root),
            )
            for class_name, name in tool_names.items()
        }

        with patches["DataQueryTools"], patches["AnalyticsTools"], \
                patches["SearchTools"], patches["ConfigManagementTools"], \
                patches["SystemManagementTools"], \
                patches["StorageSyncTools"], patches["ArticleReaderTools"]:
            first = MCPContext.create("/tmp/first")
            second = MCPContext.create("/tmp/second")

        self.assertIsNot(first, second)
        self.assertEqual(first.project_root, Path("/tmp/first").resolve())
        self.assertEqual(second.project_root, Path("/tmp/second").resolve())
        self.assertEqual(
            first.get_tool("data"),
            ("data", str(Path("/tmp/first").resolve())),
        )
        self.assertEqual(
            second.get_tool("data"),
            ("data", str(Path("/tmp/second").resolve())),
        )

    def test_create_server_returns_independent_registered_apps(self):
        context = MCPContext.from_tools(
            project_root="/tmp/project",
            tools={},
        )

        first = create_server(context=context)
        second = create_server(context=context)

        self.assertIsNot(first, second)
        self.assertEqual(
            set(asyncio.run(first.get_tools())),
            EXPECTED_TOOLS,
        )
        self.assertEqual(
            set(asyncio.run(second.get_resources())),
            EXPECTED_RESOURCES,
        )

    def test_shared_cache_is_isolated_by_project_root(self):
        cache = CacheService()
        first_parser = ParserService(
            "/tmp/first",
            query_repository=SimpleNamespace(),
        )
        second_parser = ParserService(
            "/tmp/second",
            query_repository=SimpleNamespace(),
        )
        first_parser.cache = cache
        second_parser.cache = cache

        first = DataService.__new__(DataService)
        first.parser = first_parser
        first.cache = cache
        second = DataService.__new__(DataService)
        second.parser = second_parser
        second.cache = cache

        first.parser.read_all_titles_for_date = lambda **kwargs: (
            {"source": {"first": {"ranks": [1]}}},
            {"source": "First"},
            {},
        )
        second.parser.read_all_titles_for_date = lambda **kwargs: (
            {"source": {"second": {"ranks": [1]}}},
            {"source": "Second"},
            {},
        )

        self.assertEqual(first.get_latest_news()[0]["title"], "first")
        self.assertEqual(second.get_latest_news()[0]["title"], "second")
        self.assertNotEqual(
            first_parser.cache_key("latest_news"),
            second_parser.cache_key("latest_news"),
        )


class MCPResourceContractTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        config = SimpleNamespace(
            get_current_config=lambda section: {
                "success": True,
                "config": {
                    "platforms": [{"id": "weibo", "name": "微博"}],
                    "word_groups": [["AI", "人工智能"]],
                    "total_groups": 1,
                },
                "section": section,
                "error": None,
            }
        )
        data = SimpleNamespace(
            get_rss_feeds_status=lambda: {
                "today_feeds": {"example": {"name": "Example"}}
            }
        )
        storage = SimpleNamespace(
            list_available_dates=lambda source: {
                "data": {"local": {"dates": ["2026-07-26"]}}
            }
        )
        self.context = MCPContext.from_tools(
            project_root="/tmp/project",
            tools={
                "config": config,
                "data": data,
                "storage": storage,
            },
        )

    async def _read_json_resource(self, uri):
        async with Client(create_server(context=self.context)) as client:
            result = await client.read_resource(uri)
        return json.loads(result[0].text)

    async def test_platforms_resource_reads_nested_config_payload(self):
        result = await self._read_json_resource("config://platforms")

        self.assertEqual(
            result["platforms"],
            [{"id": "weibo", "name": "微博"}],
        )

    async def test_keywords_resource_reads_nested_config_payload(self):
        result = await self._read_json_resource("config://keywords")

        self.assertEqual(result["word_groups"], [["AI", "人工智能"]])
        self.assertEqual(result["total_groups"], 1)


class MCPTransportContractTests(unittest.TestCase):
    def test_stdio_startup_does_not_write_to_stdout(self):
        fake_server = SimpleNamespace(run=lambda **kwargs: None)

        with patch(
            "mcp_server.server.create_server",
            return_value=fake_server,
        ), patch("sys.stdout.write") as stdout_write:
            run_server(project_root="/tmp/project", transport="stdio")

        stdout_write.assert_not_called()

    def test_runtime_code_never_calls_print(self):
        root = Path(__file__).parents[1] / "mcp_server"
        violations = []
        for path in root.rglob("*.py"):
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if (
                    isinstance(node, ast.Call)
                    and isinstance(node.func, ast.Name)
                    and node.func.id == "print"
                ):
                    violations.append(
                        f"{path.relative_to(root.parent)}:{node.lineno}"
                    )

        self.assertEqual(violations, [])


class MCPStdioSmokeTests(unittest.IsolatedAsyncioTestCase):
    async def test_stdio_protocol_lists_stable_surface(self):
        async def handshake():
            parameters = StdioServerParameters(
                command=sys.executable,
                args=["-m", "mcp_server.server"],
            )
            with tempfile.TemporaryFile(mode="w+") as stderr:
                async with stdio_client(
                    parameters,
                    errlog=stderr,
                ) as (read_stream, write_stream):
                    async with ClientSession(
                        read_stream,
                        write_stream,
                    ) as session:
                        await session.initialize()
                        tools = await session.list_tools()
                        resources = await session.list_resources()
            return tools, resources

        tools, resources = await asyncio.wait_for(handshake(), timeout=15)

        self.assertEqual(
            {tool.name for tool in tools.tools},
            EXPECTED_TOOLS,
        )
        self.assertEqual(
            {str(resource.uri) for resource in resources.resources},
            EXPECTED_RESOURCES,
        )


if __name__ == "__main__":
    unittest.main()
