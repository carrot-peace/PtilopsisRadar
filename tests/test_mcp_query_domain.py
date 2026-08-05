import ast
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import Mock, call, patch

from mcp_server.services.data_service import DataService
from mcp_server.tools.data_query import DataQueryTools
from mcp_server.utils.errors import DataNotFoundError, InvalidParameterError
from mcp_server.utils.validators import validate_date_range


ROOT = Path(__file__).parents[1]


class QueryFeatureBoundaryTests(unittest.TestCase):
    def test_server_delegates_query_handlers_to_feature_router(self):
        server_tree = ast.parse(
            (ROOT / "mcp_server/server.py").read_text(encoding="utf-8")
        )
        defined_functions = {
            node.name
            for node in ast.walk(server_tree)
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        }
        query_handlers = {
            "resolve_date_range",
            "get_latest_news",
            "get_trending_topics",
            "get_latest_rss",
            "search_rss",
            "get_rss_feeds_status",
            "get_news_by_date",
            "get_platforms_resource",
            "get_rss_feeds_resource",
            "get_available_dates_resource",
            "get_keywords_resource",
        }

        self.assertTrue(query_handlers.isdisjoint(defined_functions))


class DataQueryRangeContractTests(unittest.TestCase):
    @patch(
        "mcp_server.tools.data_query.validate_platforms",
        return_value=["weibo"],
    )
    def test_range_query_reads_every_date_and_keeps_legacy_summary(
        self,
        _validate_platforms,
    ):
        service = Mock()
        service.get_news_by_date_range.return_value = [
            {
                "title": "new",
                "platform": "weibo",
                "date": "2026-07-22",
            },
            {
                "title": "old",
                "platform": "weibo",
                "date": "2026-07-20",
            },
        ]
        tools = DataQueryTools(data_service=service)

        result = tools.get_news_by_date(
            date_range={
                "start": "2026-07-20",
                "end": "2026-07-22",
            },
            platforms=["weibo"],
            limit=10,
        )

        self.assertTrue(result["success"])
        self.assertEqual(
            result["summary"]["date_range"],
            {
                "start": "2026-07-20",
                "end": "2026-07-22",
            },
        )
        self.assertEqual(result["summary"]["date"], "2026-07-20")
        self.assertEqual(result["summary"]["days_requested"], 3)
        self.assertEqual(len(result["data"]), 2)
        service.get_news_by_date_range.assert_called_once_with(
            start_date=datetime(2026, 7, 20),
            end_date=datetime(2026, 7, 22),
            platforms=["weibo"],
            limit=10,
            include_url=False,
        )

    def test_query_range_is_limited_to_thirty_one_days(self):
        with self.assertRaises(InvalidParameterError):
            validate_date_range(
                {
                    "start": "2026-01-01",
                    "end": "2026-03-01",
                },
                max_days=31,
            )

    def test_single_day_relative_query_remains_supported(self):
        start_date, end_date = validate_date_range(
            "前天",
            max_days=31,
        )

        self.assertEqual(start_date.date(), end_date.date())
        self.assertEqual(
            (datetime.now().date() - start_date.date()).days,
            2,
        )

    def test_natural_range_resolves_to_all_requested_days(self):
        start_date, end_date = validate_date_range(
            "最近7天",
            max_days=31,
        )

        self.assertEqual(end_date.date() - start_date.date(), timedelta(days=6))

    def test_historical_iso_date_keeps_unbounded_shared_compatibility(self):
        start_date, end_date = validate_date_range(
            "2020-01-01",
            max_days=31,
        )

        self.assertEqual(start_date, datetime(2020, 1, 1))
        self.assertEqual(end_date, datetime(2020, 1, 1))

    def test_nonpositive_natural_ranges_are_invalid_parameters(self):
        for expression in ("最近0天", "last 0 days"):
            with self.subTest(expression=expression):
                with self.assertRaises(InvalidParameterError):
                    validate_date_range(expression, max_days=31)

    def test_rss_day_bounds_fail_instead_of_silently_clamping(self):
        service = Mock()
        tools = DataQueryTools(data_service=service)

        latest = tools.get_latest_rss(days=31)
        search = tools.search_rss(keyword="AI", days=0)

        self.assertFalse(latest["success"])
        self.assertEqual(latest["error"]["code"], "INVALID_PARAMETER")
        self.assertFalse(search["success"])
        self.assertEqual(search["error"]["code"], "INVALID_PARAMETER")
        service.get_latest_rss.assert_not_called()
        service.search_rss.assert_not_called()


class DataServiceRangeTests(unittest.TestCase):
    def test_range_reads_latest_date_first_and_skips_missing_dates(self):
        service = DataService.__new__(DataService)
        service.get_news_by_date = Mock(
            side_effect=[
                [
                    {
                        "title": "new",
                        "rank": 1,
                        "date": "2026-07-22",
                    }
                ],
                DataNotFoundError("missing"),
                [
                    {
                        "title": "old",
                        "rank": 2,
                        "date": "2026-07-20",
                    }
                ],
            ]
        )

        result = service.get_news_by_date_range(
            start_date=datetime(2026, 7, 20),
            end_date=datetime(2026, 7, 22),
            platforms=["weibo"],
            limit=10,
            include_url=True,
        )

        self.assertEqual(
            [item["title"] for item in result],
            ["new", "old"],
        )
        self.assertEqual(
            service.get_news_by_date.call_args_list,
            [
                call(
                    target_date=datetime(2026, 7, 22),
                    platforms=["weibo"],
                    limit=10,
                    include_url=True,
                ),
                call(
                    target_date=datetime(2026, 7, 21),
                    platforms=["weibo"],
                    limit=10,
                    include_url=True,
                ),
                call(
                    target_date=datetime(2026, 7, 20),
                    platforms=["weibo"],
                    limit=10,
                    include_url=True,
                ),
            ],
        )

    def test_range_raises_when_no_date_has_data(self):
        service = DataService.__new__(DataService)
        service.get_news_by_date = Mock(
            side_effect=DataNotFoundError("missing")
        )

        with self.assertRaises(DataNotFoundError):
            service.get_news_by_date_range(
                start_date=datetime(2026, 7, 20),
                end_date=datetime(2026, 7, 21),
                limit=10,
            )


if __name__ == "__main__":
    unittest.main()
