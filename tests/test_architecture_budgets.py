import ast
import unittest
from pathlib import Path


ROOT = Path(__file__).parents[1]


class SourceBudgetTests(unittest.TestCase):
    def _lines(self, relative):
        return len(
            (ROOT / relative).read_text(encoding="utf-8").splitlines()
        )

    def test_no_production_python_file_exceeds_global_ceiling(self):
        oversized = {}
        for root_name in ("trendradar", "mcp_server"):
            for path in (ROOT / root_name).rglob("*.py"):
                if "__pycache__" in path.parts:
                    continue
                line_count = len(
                    path.read_text(encoding="utf-8").splitlines()
                )
                if line_count > 1800:
                    oversized[str(path.relative_to(ROOT))] = line_count
        self.assertEqual(oversized, {})

    def test_refactored_hotspots_have_stricter_budgets(self):
        budgets = {
            "trendradar/__main__.py": 1600,
            "trendradar/application/diagnostics.py": 350,
            "trendradar/storage/sqlite_mixin.py": 200,
            "trendradar/storage/sqlite/news.py": 700,
            "trendradar/storage/sqlite/rss.py": 500,
            "trendradar/storage/sqlite/schedule.py": 120,
            "trendradar/storage/sqlite/ai_filter.py": 550,
            "mcp_server/services/parser_service.py": 300,
            "mcp_server/tools/analytics.py": 150,
            "mcp_server/tools/analytics_insights.py": 900,
            "mcp_server/tools/analytics_search.py": 500,
            "mcp_server/tools/analytics_trends.py": 750,
            "mcp_server/tools/analytics_aggregation.py": 750,
        }
        violations = {
            path: (self._lines(path), budget)
            for path, budget in budgets.items()
            if self._lines(path) > budget
        }
        self.assertEqual(violations, {})

    def test_new_application_modules_stay_cohesive(self):
        violations = {}
        for path in (ROOT / "trendradar/application").rglob("*.py"):
            line_count = len(
                path.read_text(encoding="utf-8").splitlines()
            )
            if line_count > 500:
                violations[str(path.relative_to(ROOT))] = line_count
        self.assertEqual(violations, {})


class ArchitectureDependencyTests(unittest.TestCase):
    def test_split_analytics_facade_preserves_tool_surface(self):
        from mcp_server.tools.analytics import AnalyticsTools

        expected = {
            "analyze_data_insights_unified",
            "analyze_topic_trend_unified",
            "get_topic_trend_analysis",
            "compare_platforms",
            "analyze_keyword_cooccurrence",
            "analyze_sentiment",
            "find_similar_news",
            "search_by_entity",
            "generate_summary_report",
            "get_platform_activity_stats",
            "analyze_topic_lifecycle",
            "detect_viral_topics",
            "predict_trending_topics",
            "aggregate_news",
            "compare_periods",
        }
        self.assertTrue(
            expected.issubset(
                {
                    name
                    for name in dir(AnalyticsTools)
                    if callable(getattr(AnalyticsTools, name))
                }
            )
        )

    def test_main_does_not_import_storage_implementations(self):
        tree = ast.parse(
            (ROOT / "trendradar/__main__.py").read_text(
                encoding="utf-8"
            )
        )
        imports = {
            node.module or ""
            for node in ast.walk(tree)
            if isinstance(node, ast.ImportFrom)
        }
        self.assertFalse(
            any(
                module.startswith("trendradar.storage.")
                for module in imports
            )
        )

    def test_mcp_tools_depend_on_role_specific_services(self):
        expectations = {
            "mcp_server/tools/search_tools.py": (
                "services.search_service",
                "DataService",
                "ParserService",
            ),
            "mcp_server/tools/analytics.py": (
                "services.analytics_service",
                "DataService",
                "ParserService",
            ),
        }
        for relative, (
            expected_module,
            forbidden_data,
            forbidden_parser,
        ) in expectations.items():
            source = (ROOT / relative).read_text(encoding="utf-8")
            tree = ast.parse(source)
            modules = {
                node.module or ""
                for node in ast.walk(tree)
                if isinstance(node, ast.ImportFrom)
            }
            imported_names = {
                alias.name
                for node in ast.walk(tree)
                if isinstance(node, ast.ImportFrom)
                for alias in node.names
            }
            self.assertIn(expected_module, modules)
            self.assertNotIn(forbidden_data, imported_names)
            self.assertNotIn(forbidden_parser, imported_names)


if __name__ == "__main__":
    unittest.main()
