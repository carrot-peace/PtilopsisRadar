import unittest
from types import SimpleNamespace
from unittest.mock import Mock


def _request(**overrides):
    from trendradar.application.run_state import AnalysisRequest

    values = {
        "mode": "daily",
        "results": {"source": {"title": {}}},
        "id_to_name": {"source": "Source"},
        "failed_ids": (),
        "title_info": {"source": {}},
        "new_titles": {"source": []},
        "word_groups": ({"word": "topic"},),
        "filter_words": ("skip",),
        "global_filters": ("global",),
        "rss_items": [{"title": "rss"}],
        "rss_new_urls": frozenset({"https://example.com/new"}),
    }
    values.update(overrides)
    return AnalysisRequest(**values)


class AnalysisServiceTests(unittest.TestCase):
    def test_keyword_filter_has_typed_input_and_output(self):
        from trendradar.application.services.analysis import (
            AnalysisSelection,
            AnalysisService,
        )

        context = SimpleNamespace(
            count_frequency=Mock(
                return_value=([{"word": "topic", "count": 2}], 7)
            ),
        )

        result = AnalysisService(context).analyze(
            _request(),
            filter_method="keyword",
        )

        self.assertIsInstance(result, AnalysisSelection)
        self.assertEqual(result.total_titles, 7)
        self.assertEqual(result.filter_method, "keyword")
        self.assertFalse(result.fell_back)
        self.assertEqual(result.rss_items, [{"title": "rss"}])
        context.count_frequency.assert_called_once_with(
            {"source": {"title": {}}},
            ({"word": "topic"},),
            ("skip",),
            {"source": "Source"},
            {"source": {}},
            {"source": []},
            mode="daily",
            global_filters=("global",),
            quiet=False,
        )

    def test_successful_ai_filter_replaces_matching_rss(self):
        from trendradar.application.services.analysis import AnalysisService

        ai_result = SimpleNamespace(
            success=True,
            total_matched=3,
            tags=("one", "two"),
        )
        context = SimpleNamespace(
            run_ai_filter=Mock(return_value=ai_result),
            convert_ai_filter_to_report_data=Mock(
                return_value=(
                    [{"word": "ai", "count": 3}],
                    [{"word": "rss-ai", "count": 1}],
                )
            ),
            count_frequency=Mock(),
        )

        result = AnalysisService(context).analyze(
            _request(),
            filter_method="ai",
            interests_file="interests.md",
        )

        self.assertEqual(result.filter_method, "ai")
        self.assertFalse(result.fell_back)
        self.assertEqual(result.total_titles, 1)
        self.assertEqual(result.rss_items, [{"word": "rss-ai", "count": 1}])
        context.run_ai_filter.assert_called_once_with(
            interests_file="interests.md"
        )
        context.convert_ai_filter_to_report_data.assert_called_once_with(
            ai_result,
            mode="daily",
            new_titles={"source": []},
            rss_new_urls=frozenset({"https://example.com/new"}),
        )
        context.count_frequency.assert_not_called()

    def test_failed_ai_filter_falls_back_to_keyword(self):
        from trendradar.application.services.analysis import AnalysisService

        context = SimpleNamespace(
            run_ai_filter=Mock(
                return_value=SimpleNamespace(
                    success=False,
                    error="provider unavailable",
                )
            ),
            count_frequency=Mock(
                return_value=([{"word": "fallback", "count": 1}], 5)
            ),
        )

        result = AnalysisService(context).analyze(
            _request(),
            filter_method="ai",
        )

        self.assertEqual(result.filter_method, "keyword")
        self.assertTrue(result.fell_back)
        self.assertEqual(result.total_titles, 5)
        context.count_frequency.assert_called_once()


class AnalysisOutcomeTests(unittest.TestCase):
    def test_outcome_replaces_positional_pipeline_tuple(self):
        from trendradar.application.run_state import AnalysisOutcome

        outcome = AnalysisOutcome(
            stats=[{"word": "topic", "count": 1}],
            total_titles=4,
            html_file="report.html",
            ai_result=None,
            rss_items=[{"word": "rss", "count": 2}],
            rss_matched_count=2,
        )

        self.assertEqual(outcome.html_file, "report.html")
        self.assertEqual(outcome.total_titles, 4)
        self.assertEqual(outcome.rss_matched_count, 2)


if __name__ == "__main__":
    unittest.main()
