import unittest
from types import SimpleNamespace
from unittest.mock import Mock

from trendradar.ai import AIAnalysisResult
from trendradar.core.scheduler import ResolvedSchedule


def _schedule(**overrides):
    values = {
        "period_key": None,
        "period_name": None,
        "day_plan": "manual",
        "collect": True,
        "analyze": True,
        "report_mode": "current",
        "ai_mode": "current",
        "once_analyze": False,
    }
    values.update(overrides)
    return ResolvedSchedule(**values)


class AIAnalysisServiceTests(unittest.TestCase):
    def _context(self, *, enabled=True, mode="follow_report"):
        scheduler = SimpleNamespace(
            already_executed=Mock(return_value=False),
            record_execution=Mock(),
        )
        context = SimpleNamespace(
            config={
                "AI_ANALYSIS": {"ENABLED": enabled, "MODE": mode},
                "AI": {},
                "DEBUG": False,
                "BACKGROUND_PULL_ONLY": False,
            },
            get_time=Mock(return_value=None),
            format_date=Mock(return_value="2026-07-24"),
            create_scheduler=Mock(return_value=scheduler),
            source_tier_resolver="tiers",
        )
        return context, scheduler

    def _request(self):
        from trendradar.application.services.ai import AIAnalysisRequest

        return AIAnalysisRequest(
            stats=[{"word": "current", "titles": [{"title": "current"}]}],
            rss_items=[],
            mode="current",
            report_type="当前榜单",
            id_to_name={"source": "Source"},
            current_results={"source": {}},
        )

    def test_disabled_service_has_no_analyzer_side_effect(self):
        from trendradar.application.services.ai import AIAnalysisService

        context, _ = self._context(enabled=False)
        analyzer_factory = Mock()
        service = AIAnalysisService(
            context,
            prepare_mode_data=Mock(),
            analyzer_factory=analyzer_factory,
        )

        self.assertIsNone(service.run(self._request(), _schedule()))
        analyzer_factory.assert_not_called()

    def test_schedule_skip_happens_before_analyzer_creation(self):
        from trendradar.application.services.ai import AIAnalysisService

        context, _ = self._context()
        analyzer_factory = Mock()
        service = AIAnalysisService(
            context,
            prepare_mode_data=Mock(),
            analyzer_factory=analyzer_factory,
        )

        self.assertIsNone(
            service.run(self._request(), _schedule(analyze=False))
        )
        analyzer_factory.assert_not_called()

    def test_alternate_mode_prepares_data_and_records_once_success(self):
        from trendradar.application.services.ai import AIAnalysisService

        context, scheduler = self._context()
        prepare = Mock(
            return_value=(
                [{"word": "daily", "titles": [{"title": "daily"}]}],
                {"source": "Source"},
            )
        )
        analyzer = SimpleNamespace(
            analyze=Mock(return_value=AIAnalysisResult(success=True))
        )
        service = AIAnalysisService(
            context,
            prepare_mode_data=prepare,
            analyzer_factory=Mock(return_value=analyzer),
        )
        schedule = _schedule(
            period_key="morning",
            period_name="Morning",
            ai_mode="daily",
            once_analyze=True,
        )

        result = service.run(self._request(), schedule)

        self.assertTrue(result.success)
        self.assertEqual(result.ai_mode, "daily")
        prepare.assert_called_once_with(
            "daily",
            {"source": {}},
            {"source": "Source"},
        )
        self.assertEqual(analyzer.analyze.call_args.kwargs["report_mode"], "daily")
        self.assertEqual(
            analyzer.analyze.call_args.kwargs["report_type"],
            "当日汇总",
        )
        scheduler.record_execution.assert_called_once_with(
            "morning",
            "analyze",
            "2026-07-24",
        )

    def test_once_schedule_dedupe_skips_prepare_and_analyzer(self):
        from trendradar.application.services.ai import AIAnalysisService

        context, scheduler = self._context()
        scheduler.already_executed.return_value = True
        prepare = Mock()
        analyzer_factory = Mock()
        service = AIAnalysisService(
            context,
            prepare_mode_data=prepare,
            analyzer_factory=analyzer_factory,
        )

        result = service.run(
            self._request(),
            _schedule(period_key="morning", once_analyze=True),
        )

        self.assertIsNone(result)
        prepare.assert_not_called()
        analyzer_factory.assert_not_called()
        scheduler.record_execution.assert_not_called()


if __name__ == "__main__":
    unittest.main()
