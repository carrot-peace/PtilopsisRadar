import ast
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import Mock


ROOT = Path(__file__).parents[1]


class MCPServiceBoundaryTests(unittest.TestCase):
    def test_search_service_owns_news_rss_and_date_reads(self):
        from mcp_server.services.search_service import SearchService

        parser = Mock()
        parser.read_all_titles_for_date.side_effect = [
            ("news", "names", "times"),
            ("rss", "feeds", "times"),
        ]
        parser.get_available_date_range.return_value = ("first", "last")
        service = SearchService(parser=parser)
        date = datetime(2026, 7, 24)

        self.assertEqual(
            service.read_news(date=date, platforms=["weibo"]),
            ("news", "names", "times"),
        )
        self.assertEqual(
            service.read_rss(date=date),
            ("rss", "feeds", "times"),
        )
        self.assertEqual(
            service.get_available_date_range(),
            ("first", "last"),
        )
        self.assertEqual(
            parser.read_all_titles_for_date.call_args_list[0].kwargs,
            {
                "date": date,
                "platform_ids": ["weibo"],
            },
        )
        self.assertEqual(
            parser.read_all_titles_for_date.call_args_list[1].kwargs,
            {
                "date": date,
                "platform_ids": None,
                "db_type": "rss",
            },
        )

    def test_analytics_service_exposes_only_news_snapshots(self):
        from mcp_server.services.analytics_service import AnalyticsService

        parser = Mock()
        parser.read_all_titles_for_date.return_value = (
            "news",
            "names",
            "times",
        )
        service = AnalyticsService(parser=parser)
        date = datetime(2026, 7, 24)

        self.assertEqual(
            service.read_news(date=date, platforms=["zhihu"]),
            ("news", "names", "times"),
        )
        parser.read_all_titles_for_date.assert_called_once_with(
            date=date,
            platform_ids=["zhihu"],
        )
        self.assertFalse(hasattr(service, "read_rss"))

    def test_tools_do_not_reach_through_data_service_parser(self):
        for relative in (
            "mcp_server/tools/search_tools.py",
            "mcp_server/tools/analytics.py",
        ):
            source = (ROOT / relative).read_text(encoding="utf-8")
            tree = ast.parse(source)
            attributes = {
                ".".join(
                    reversed(
                        self._attribute_parts(node)
                    )
                )
                for node in ast.walk(tree)
                if isinstance(node, ast.Attribute)
            }
            self.assertNotIn("self.data_service.parser", attributes)

    @staticmethod
    def _attribute_parts(node):
        parts = []
        while isinstance(node, ast.Attribute):
            parts.append(node.attr)
            node = node.value
        if isinstance(node, ast.Name):
            parts.append(node.id)
        return parts

    def test_search_tool_accepts_role_specific_service(self):
        from mcp_server.tools.search_tools import SearchTools

        service = Mock()
        service.get_available_date_range.return_value = (None, None)

        result = SearchTools(search_service=service).search_news_unified(
            "topic"
        )

        self.assertFalse(result["success"])
        service.get_available_date_range.assert_called_once_with()

    def test_analytics_tool_accepts_role_specific_service(self):
        from mcp_server.tools.analytics import AnalyticsTools

        service = Mock()
        service.read_news.return_value = (
            {"source": {"topic": {"ranks": [1]}}},
            {"source": "Source"},
            {},
        )

        result = AnalyticsTools(
            analytics_service=service
        ).search_by_entity("topic")

        self.assertTrue(result["success"])
        service.read_news.assert_called_once_with()


if __name__ == "__main__":
    unittest.main()
