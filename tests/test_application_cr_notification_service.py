import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch


class CRNotificationServiceTests(unittest.TestCase):
    def _request(self):
        from trendradar.application.services.cr_notification import (
            CRNotificationRequest,
        )

        return CRNotificationRequest(
            mode="current",
            hotlist_stats=[],
            rss_stats=[],
            raw_rss_items=None,
            hotlist_configured_ids=frozenset({"source"}),
            hotlist_successful_ids=frozenset({"source"}),
            hotlist_failed_ids=frozenset(),
            rss_configured_ids=frozenset(),
            rss_successful_ids=frozenset(),
            rss_failed_ids=frozenset(),
            observed_item_identities=frozenset(),
            snapshot_generated_at=None,
            historical_data_reused=False,
        )

    def test_off_mode_has_no_context_side_effect(self):
        from trendradar.application.services.cr_notification import (
            CRNotificationService,
        )

        context = SimpleNamespace(get_time=Mock())
        service = CRNotificationService(
            context,
            environ={"PTILOPSIS_CR_DISPATCH_MODE": "off"},
        )

        result = service.run(self._request())

        self.assertFalse(result.executed)
        self.assertEqual(result.mode, "off")
        context.get_time.assert_not_called()

    def test_news_analyzer_facade_builds_request_from_single_run_state(self):
        import trendradar.__main__ as application
        from trendradar.application.run_state import RunState

        state = RunState.create(
            hotlist_configured_ids={"hot"},
            rss_configured_ids={"rss"},
        )
        state.hotlist.successful_ids.add("hot")
        state.rss.failed_ids.add("rss")
        state.observed_item_identities.add("identity")
        state.input_snapshot_generated_at = "2026-07-24T09:30:00+08:00"
        analyzer = SimpleNamespace(ctx="context", run_state=state)

        with patch(
            "trendradar.application.services.cr_notification."
            "CRNotificationService.run",
            return_value="result",
        ) as run:
            result = application.NewsAnalyzer._run_cr_dispatch_hook(
                analyzer,
                mode="current",
                stats=[{"word": "topic"}],
                rss_items=[{"word": "rss"}],
            )

        self.assertEqual(result, "result")
        request = run.call_args.args[0]
        self.assertEqual(request.mode, "current")
        self.assertEqual(request.hotlist_successful_ids, frozenset({"hot"}))
        self.assertEqual(request.rss_failed_ids, frozenset({"rss"}))
        self.assertEqual(
            request.observed_item_identities,
            frozenset({"identity"}),
        )


if __name__ == "__main__":
    unittest.main()
