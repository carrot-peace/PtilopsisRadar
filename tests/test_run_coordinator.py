import unittest
from types import SimpleNamespace
from unittest.mock import Mock


def _plan(*, collect=True):
    return SimpleNamespace(collect=collect, report_mode="daily")


class RunCoordinatorTests(unittest.TestCase):
    def _application(self, *, collect=True):
        events = []
        context = SimpleNamespace(
            run_retention_maintenance=Mock(
                side_effect=lambda: events.append("retention")
            ),
            close=Mock(side_effect=lambda: events.append("close")),
        )
        application = SimpleNamespace(
            ctx=context,
            run_state="old",
            _initialize_and_check_config=Mock(
                side_effect=lambda: events.append("initialize") or True
            ),
            _resolve_run_plan=Mock(
                side_effect=lambda: events.append("plan")
                or _plan(collect=collect)
            ),
            _new_run_state=Mock(
                side_effect=lambda: events.append("state") or "new"
            ),
            _crawl_data=Mock(
                side_effect=lambda: events.append("hotlist")
                or ({"source": {}}, {"source": "Source"}, [])
            ),
            _crawl_rss_data=Mock(
                side_effect=lambda plan: events.append("rss")
                or (None, None, None, set())
            ),
            _execute_mode_strategy=Mock(
                side_effect=lambda *args, **kwargs: events.append("analysis")
                or "report.html"
            ),
        )
        return application, events

    def test_successful_run_owns_order_state_and_lifecycle(self):
        from trendradar.application.coordinator import RunCoordinator

        application, events = self._application()

        result = RunCoordinator(application).run()

        self.assertEqual(result.status, "completed")
        self.assertEqual(result.html_file, "report.html")
        self.assertEqual(application.run_state, "new")
        self.assertEqual(
            events,
            [
                "initialize",
                "plan",
                "state",
                "hotlist",
                "rss",
                "analysis",
                "retention",
                "close",
            ],
        )

    def test_collect_false_skips_state_and_all_acquisition(self):
        from trendradar.application.coordinator import RunCoordinator

        application, events = self._application(collect=False)

        result = RunCoordinator(application).run()

        self.assertEqual(result.status, "skipped")
        self.assertEqual(events, ["initialize", "plan", "close"])
        application._new_run_state.assert_not_called()
        application.ctx.run_retention_maintenance.assert_not_called()

    def test_failure_still_runs_retention_then_close_and_propagates(self):
        from trendradar.application.coordinator import RunCoordinator

        application, events = self._application()
        application._crawl_data.side_effect = lambda: (
            events.append("hotlist"),
            (_ for _ in ()).throw(RuntimeError("injected")),
        )[1]

        with self.assertRaisesRegex(RuntimeError, "injected"):
            RunCoordinator(application).run()

        self.assertEqual(
            events,
            [
                "initialize",
                "plan",
                "state",
                "hotlist",
                "retention",
                "close",
            ],
        )


if __name__ == "__main__":
    unittest.main()
