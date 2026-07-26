import unittest
from types import SimpleNamespace
from unittest.mock import Mock


class DRNotificationServiceTests(unittest.TestCase):
    def _context(self):
        return SimpleNamespace(
            format_date=Mock(return_value="2026-07-24"),
            get_time=Mock(),
            create_scheduler=Mock(),
        )

    def test_off_mode_has_no_context_or_artifact_side_effect(self):
        from trendradar.application.services.dr_notification import (
            DRNotificationService,
        )

        context = self._context()
        service = DRNotificationService(
            context,
            environ={"PTILOPSIS_DR_DISPATCH_MODE": "off"},
        )

        result = service.run(
            ai_result=object(),
            html_file="report.html",
            schedule=None,
        )

        self.assertFalse(result.executed)
        self.assertEqual(result.mode, "off")
        context.format_date.assert_not_called()
        context.get_time.assert_not_called()

if __name__ == "__main__":
    unittest.main()
