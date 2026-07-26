import unittest
from types import SimpleNamespace
from unittest.mock import Mock


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

if __name__ == "__main__":
    unittest.main()
