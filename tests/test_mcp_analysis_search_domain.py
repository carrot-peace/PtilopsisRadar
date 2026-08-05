import asyncio
import ast
import hashlib
import json
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import Mock, call, patch

from mcp_server.server import mcp
from mcp_server.tools.analytics import AnalyticsTools
from mcp_server.tools.search_tools import SearchTools


ROOT = Path(__file__).parents[1]
PUBLIC_HANDLERS = {
    "analyze_topic_trend",
    "analyze_data_insights",
    "analyze_sentiment",
    "find_related_news",
    "generate_summary_report",
    "aggregate_news",
    "compare_periods",
    "search_news",
}
EXPECTED_DESCRIPTION_DIGEST = (
    "97888b9059ab788b839bdfcf5dd3a82e739ba857263f45930315fac599558cfe"
)


class AnalysisSearchFeatureBoundaryTests(unittest.TestCase):
    def test_server_delegates_analysis_and_search_handlers(self):
        server_tree = ast.parse(
            (ROOT / "mcp_server/server.py").read_text(encoding="utf-8")
        )
        defined_functions = {
            node.name
            for node in ast.walk(server_tree)
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        }
        self.assertTrue(PUBLIC_HANDLERS.isdisjoint(defined_functions))

    def test_public_parameter_guidance_is_stable(self):
        tools = asyncio.run(mcp.get_tools())
        descriptions = {
            name: tools[name].description
            for name in sorted(PUBLIC_HANDLERS)
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


class TopicAnalysisContractTests(unittest.TestCase):
    def test_unified_viral_analysis_forwards_topic_and_window(self):
        tools = AnalyticsTools(analytics_service=Mock())
        tools.detect_viral_topics = Mock(
            return_value={"success": True, "data": []}
        )

        result = tools.analyze_topic_trend_unified(
            topic="AI",
            analysis_type="viral",
            threshold=2.0,
            time_window=48,
        )

        self.assertTrue(result["success"])
        tools.detect_viral_topics.assert_called_once_with(
            topic="AI",
            threshold=2.0,
            time_window=48,
        )

    def test_unified_prediction_forwards_topic_and_horizon(self):
        tools = AnalyticsTools(analytics_service=Mock())
        tools.predict_trending_topics = Mock(
            return_value={"success": True, "data": []}
        )

        result = tools.analyze_topic_trend_unified(
            topic="AI",
            analysis_type="predict",
            lookahead_hours=12,
            confidence_threshold=0.7,
        )

        self.assertTrue(result["success"])
        tools.predict_trending_topics.assert_called_once_with(
            topic="AI",
            lookahead_hours=12,
            confidence_threshold=0.7,
        )

    @patch("mcp_server.tools.analytics_trends.datetime")
    def test_viral_window_selects_the_matching_daily_baseline(
        self,
        mock_datetime,
    ):
        now = datetime(2026, 7, 26, 12)
        mock_datetime.now.return_value = now
        service = Mock()
        service.read_news.side_effect = [
            (
                {
                    "source": {
                        f"AI current {index}": {}
                        for index in range(5)
                    }
                },
                {},
                {},
            ),
            (
                {"source": {"AI baseline": {}}},
                {},
                {},
            ),
        ]
        tools = AnalyticsTools(analytics_service=service)

        result = tools.detect_viral_topics(
            topic="AI",
            threshold=2.0,
            time_window=48,
        )

        self.assertTrue(result["success"])
        self.assertEqual(result["data"][0]["keyword"], "AI")
        self.assertEqual(
            service.read_news.call_args_list,
            [
                call(),
                call(date=now - timedelta(days=2)),
            ],
        )

    @patch("mcp_server.tools.analytics_trends.datetime")
    def test_prediction_horizon_changes_projected_count(
        self,
        mock_datetime,
    ):
        now = datetime(2026, 7, 26, 12)
        mock_datetime.now.return_value = now

        def make_service():
            service = Mock()
            service.read_news.side_effect = [
                self._snapshot("AI", count)
                for count in (1, 2, 3, 4)
            ]
            return service

        short = AnalyticsTools(
            analytics_service=make_service()
        ).predict_trending_topics(
            topic="AI",
            lookahead_hours=12,
            confidence_threshold=0.7,
        )
        long = AnalyticsTools(
            analytics_service=make_service()
        ).predict_trending_topics(
            topic="AI",
            lookahead_hours=24,
            confidence_threshold=0.7,
        )

        self.assertTrue(short["success"])
        self.assertTrue(long["success"])
        self.assertEqual(short["data"][0]["keyword"], "AI")
        self.assertLess(
            short["data"][0]["projected_count"],
            long["data"][0]["projected_count"],
        )

    @staticmethod
    def _snapshot(topic, count):
        return (
            {
                "source": {
                    f"{topic} item {index}": {}
                    for index in range(count)
                }
            },
            {},
            {},
        )


class SharedTextPolicyTests(unittest.TestCase):
    def test_similarity_keeps_each_feature_case_policy(self):
        search = SearchTools.__new__(SearchTools)
        analytics = AnalyticsTools.__new__(AnalyticsTools)

        self.assertEqual(search._calculate_similarity("AI", "ai"), 1.0)
        self.assertLess(
            analytics._calculate_similarity("AI", "ai"),
            1.0,
        )

    def test_keyword_extraction_keeps_each_feature_policy(self):
        search = SearchTools.__new__(SearchTools)
        analytics = AnalyticsTools.__new__(AnalyticsTools)

        self.assertEqual(
            search._extract_keywords("AI [beta] news"),
            ["AI", "news"],
        )
        self.assertEqual(
            analytics._extract_keywords("AI，的 news"),
            ["AI", "news"],
        )

    def test_search_jaccard_wrappers_share_one_policy(self):
        search = SearchTools.__new__(SearchTools)

        self.assertEqual(
            search._calculate_keyword_overlap(["AI", "news"], ["AI"]),
            search._jaccard_similarity(["AI", "news"], ["AI"]),
        )


if __name__ == "__main__":
    unittest.main()
