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
            "mcp_server/services/data_service.py": 900,
            "mcp_server/context.py": 150,
            "mcp_server/server.py": 450,
            "mcp_server/domain/text.py": 100,
            "mcp_server/features/analysis_search.py": 250,
            "mcp_server/features/query.py": 300,
            "mcp_server/tools/data_query.py": 550,
            "mcp_server/tools/search_tools.py": 910,
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
    @staticmethod
    def _imported_modules(tree, *, package=None):
        modules = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                modules.update(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom):
                module = node.module or ""
                if node.level:
                    if not package:
                        raise ValueError(
                            "package is required for relative imports"
                        )
                    package_parts = package.split(".")
                    keep = len(package_parts) - (node.level - 1)
                    if keep < 0:
                        raise ValueError("relative import escapes package")
                    module_parts = package_parts[:keep]
                    if module:
                        module_parts.append(module)
                    module = ".".join(module_parts)
                if module:
                    modules.add(module)
                modules.update(
                    f"{module}.{alias.name}" if module else alias.name
                    for alias in node.names
                )
        return modules

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
        imports = self._imported_modules(tree, package="trendradar")
        self.assertFalse(
            any(
                module == "trendradar.storage"
                or module.startswith("trendradar.storage.")
                for module in imports
            )
        )

    def test_import_scanner_covers_package_and_module_imports(self):
        tree = ast.parse(
            """
from trendradar import storage
from ..services import data_service
import mcp_server.services.parser_service as parser_service
"""
        )
        self.assertEqual(
            self._imported_modules(tree, package="mcp_server.tools"),
            {
                "trendradar",
                "trendradar.storage",
                "mcp_server.services",
                "mcp_server.services.data_service",
                "mcp_server.services.parser_service",
            },
        )

    def test_import_scanner_resolves_package_relative_imports(self):
        tree = ast.parse(
            """
from .storage import LocalStorageBackend
from . import storage
"""
        )
        self.assertEqual(
            self._imported_modules(tree, package="trendradar"),
            {
                "trendradar",
                "trendradar.storage",
                "trendradar.storage.LocalStorageBackend",
            },
        )

    def test_mcp_tools_depend_on_role_specific_services(self):
        expectations = {
            "mcp_server/tools/search_tools.py": (
                "mcp_server.services.search_service"
            ),
            "mcp_server/tools/analytics.py": (
                "mcp_server.services.analytics_service"
            ),
        }
        for relative, expected_module in expectations.items():
            source = (ROOT / relative).read_text(encoding="utf-8")
            tree = ast.parse(source)
            package = ".".join(Path(relative).parent.parts)
            modules = self._imported_modules(tree, package=package)
            imported_names = {
                alias.name
                for node in ast.walk(tree)
                if isinstance(node, ast.ImportFrom)
                for alias in node.names
            }
            self.assertIn(expected_module, modules)
            for forbidden_module in (
                "mcp_server.services.data_service",
                "mcp_server.services.parser_service",
            ):
                self.assertFalse(
                    any(
                        module == forbidden_module
                        or module.endswith(f".{forbidden_module}")
                        for module in modules
                    )
                )
            self.assertNotIn("DataService", imported_names)
            self.assertNotIn("ParserService", imported_names)


if __name__ == "__main__":
    unittest.main()
