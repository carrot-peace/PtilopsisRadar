import unittest
from unittest.mock import Mock


class NotificationServiceTests(unittest.TestCase):
    def test_runs_eligible_hooks_in_registration_order(self):
        from trendradar.application.services.notification import (
            NotificationHook,
            NotificationService,
        )

        events = []
        service = NotificationService()
        event = object()

        results = service.notify(
            event,
            (
                NotificationHook(
                    name="first",
                    handler=lambda value: events.append(("first", value)),
                ),
                NotificationHook(
                    name="skipped",
                    handler=lambda value: events.append(("skipped", value)),
                    predicate=lambda _value: False,
                ),
                NotificationHook(
                    name="second",
                    handler=lambda value: events.append(("second", value)),
                ),
            ),
        )

        self.assertEqual(events, [("first", event), ("second", event)])
        self.assertEqual(
            [(item.name, item.status) for item in results],
            [
                ("first", "completed"),
                ("skipped", "skipped"),
                ("second", "completed"),
            ],
        )

    def test_non_fatal_hook_failure_is_reported_and_next_hook_runs(self):
        from trendradar.application.services.notification import (
            NotificationHook,
            NotificationService,
        )

        reporter = Mock()
        next_hook = Mock()
        service = NotificationService(error_reporter=reporter)

        results = service.notify(
            object(),
            (
                NotificationHook(
                    name="broken",
                    handler=Mock(side_effect=RuntimeError("injected")),
                    suppress_exceptions=True,
                ),
                NotificationHook(name="next", handler=next_hook),
            ),
        )

        reporter.assert_called_once()
        next_hook.assert_called_once()
        self.assertEqual(results[0].status, "failed")
        self.assertEqual(results[0].error, "injected")

    def test_fatal_hook_failure_propagates(self):
        from trendradar.application.services.notification import (
            NotificationHook,
            NotificationService,
        )

        service = NotificationService()

        with self.assertRaisesRegex(RuntimeError, "fatal"):
            service.notify(
                object(),
                (
                    NotificationHook(
                        name="fatal",
                        handler=Mock(side_effect=RuntimeError("fatal")),
                    ),
                ),
            )


if __name__ == "__main__":
    unittest.main()
