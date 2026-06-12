# coding=utf-8
"""
Tests for pure CR-A event state transition preview (PR10i).
"""

import inspect
import unittest

import trendradar.cr.state_transition_preview as preview_module
from trendradar.cr.state_snapshot import (
    CR_EVENT_STATE_SCHEMA_VERSION,
    CREventStateEntry,
    CREventStateSnapshot,
)
from trendradar.cr.state_transition_preview import (
    build_cr_event_state_transition_preview,
)


def _snapshot(*entries: CREventStateEntry) -> CREventStateSnapshot:
    return CREventStateSnapshot(
        schema_version=CR_EVENT_STATE_SCHEMA_VERSION,
        entries=entries,
    )


class TestNoPriorSnapshot(unittest.TestCase):
    def test_next_snapshot_uses_current_updates_only(self):
        update = CREventStateEntry(event_key="event-a", decision_level="alert")

        preview = build_cr_event_state_transition_preview(
            prior_snapshot=None,
            state_updates=(update,),
        )

        self.assertFalse(preview.prior_snapshot_available)
        self.assertIsNone(preview.prior_snapshot_loaded)
        self.assertIsNone(preview.prior_snapshot_error)
        self.assertEqual(preview.update_count, 1)
        self.assertIsNotNone(preview.next_snapshot)
        self.assertEqual(preview.next_snapshot.entries, (update,))
        self.assertIn("current state updates only", preview.reason)


class TestValidPriorSnapshot(unittest.TestCase):
    def test_merges_prior_and_updates(self):
        prior = _snapshot(
            CREventStateEntry(
                event_key="event-a",
                decision_level="watch",
                score=50.0,
            ),
            CREventStateEntry(event_key="event-b", decision_level="alert"),
        )
        updates = (
            CREventStateEntry(
                event_key="event-a",
                decision_level="urgent",
                score=91.0,
            ),
            CREventStateEntry(event_key="event-c", decision_level="watch"),
        )

        preview = build_cr_event_state_transition_preview(
            prior_snapshot=prior,
            state_updates=updates,
            prior_snapshot_loaded=True,
        )

        self.assertTrue(preview.prior_snapshot_available)
        self.assertTrue(preview.prior_snapshot_loaded)
        self.assertIsNone(preview.prior_snapshot_error)
        self.assertEqual(preview.update_count, 2)
        self.assertIsNotNone(preview.next_snapshot)
        by_key = {
            entry.event_key: entry for entry in preview.next_snapshot.entries
        }
        self.assertEqual(
            [entry.event_key for entry in preview.next_snapshot.entries],
            ["event-a", "event-b", "event-c"],
        )
        self.assertEqual(by_key["event-a"].decision_level, "urgent")
        self.assertEqual(by_key["event-a"].score, 91.0)
        self.assertEqual(by_key["event-b"].decision_level, "alert")
        self.assertEqual(by_key["event-c"].decision_level, "watch")
        self.assertIn("merged", preview.reason)


class TestPriorLoadError(unittest.TestCase):
    def test_error_suppresses_next_snapshot_preview(self):
        update = CREventStateEntry(event_key="event-a", decision_level="alert")

        preview = build_cr_event_state_transition_preview(
            prior_snapshot=None,
            state_updates=(update,),
            prior_snapshot_loaded=False,
            prior_snapshot_error="invalid event state snapshot",
        )

        self.assertFalse(preview.prior_snapshot_available)
        self.assertFalse(preview.prior_snapshot_loaded)
        self.assertEqual(
            preview.prior_snapshot_error,
            "invalid event state snapshot",
        )
        self.assertEqual(preview.update_count, 1)
        self.assertIsNone(preview.next_snapshot)
        self.assertIn("suppressed", preview.reason)


class TestPurityGuard(unittest.TestCase):
    def test_module_source_has_no_forbidden_io_network_env_or_runtime(self):
        source = inspect.getsource(preview_module)
        forbidden = (
            "open(",
            "Path(",
            "os.environ",
            "datetime.now",
            "time.time",
            "state_store",
            "telegram",
            "dispatch",
            "config",
            "requests",
            "httpx",
            "aiohttp",
            "urlopen",
        )
        for token in forbidden:
            self.assertNotIn(token, source, f"forbidden token {token!r}")


if __name__ == "__main__":
    unittest.main()
