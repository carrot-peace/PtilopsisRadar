# coding=utf-8
"""
Tests for CR-A repeat preview evidence (PR10b).

The module under test is pure and preview-only: it classifies repeat semantics
against an explicitly supplied in-memory snapshot and does not suppress,
persist, fetch, or send anything.
"""

import inspect
import unittest
from dataclasses import replace

from trendradar.cr.repeat_preview import (
    CRSeenEventState,
    compare_cr_decision_level,
    normalize_cr_decision_level,
    preview_cr_repeat,
    preview_cr_repeats,
)
import trendradar.cr.repeat_preview as repeat_preview_module


class TestDecisionLevelNormalization(unittest.TestCase):
    def test_preserves_known_levels(self):
        self.assertEqual(normalize_cr_decision_level("suppress"), "suppress")
        self.assertEqual(normalize_cr_decision_level("watch"), "watch")
        self.assertEqual(normalize_cr_decision_level("alert"), "alert")
        self.assertEqual(normalize_cr_decision_level("urgent"), "urgent")

    def test_trims_and_lowercases_existing_labels(self):
        self.assertEqual(normalize_cr_decision_level(" Alert "), "alert")

    def test_unknown_and_none_return_none(self):
        self.assertIsNone(normalize_cr_decision_level("notify"))
        self.assertIsNone(normalize_cr_decision_level(""))
        self.assertIsNone(normalize_cr_decision_level(None))


class TestDecisionLevelComparison(unittest.TestCase):
    def test_watch_to_alert_is_escalation(self):
        self.assertEqual(compare_cr_decision_level("watch", "alert"), "escalation")

    def test_alert_to_urgent_is_escalation(self):
        self.assertEqual(compare_cr_decision_level("alert", "urgent"), "escalation")

    def test_urgent_to_alert_is_deescalation(self):
        self.assertEqual(compare_cr_decision_level("urgent", "alert"), "deescalation")

    def test_alert_to_alert_is_same(self):
        self.assertEqual(compare_cr_decision_level("alert", "alert"), "same")

    def test_unknown_is_unknown(self):
        self.assertEqual(compare_cr_decision_level(None, "alert"), "unknown")
        self.assertEqual(compare_cr_decision_level("alert", None), "unknown")


class TestSinglePreview(unittest.TestCase):
    def test_no_snapshot_is_not_evaluated(self):
        preview = preview_cr_repeat(
            event_key="e1",
            current_decision_level="alert",
            current_score=70.0,
        )
        self.assertEqual(preview.status, "not_evaluated")
        self.assertEqual(preview.reason, "no prior event state snapshot provided")

    def test_snapshot_provided_but_key_absent_is_new(self):
        preview = preview_cr_repeat(
            event_key="e1",
            current_decision_level="alert",
            current_score=70.0,
            prior_state_snapshot_provided=True,
        )
        self.assertEqual(preview.status, "new")
        self.assertEqual(
            preview.reason,
            "event key not present in prior state snapshot",
        )

    def test_same_event_same_level_is_same_level_repeat(self):
        state = CRSeenEventState(event_key="e1", decision_level="alert", score=65.0)
        preview = preview_cr_repeat(
            event_key="e1",
            current_decision_level="alert",
            current_score=67.0,
            seen_state=state,
            prior_state_snapshot_provided=True,
        )
        self.assertEqual(preview.status, "same_level_repeat")
        self.assertEqual(preview.previous_decision_level, "alert")
        self.assertEqual(preview.current_decision_level, "alert")
        self.assertEqual(preview.previous_score, 65.0)
        self.assertEqual(preview.current_score, 67.0)

    def test_same_event_escalation_is_meaningful_escalation(self):
        state = CRSeenEventState(event_key="e1", decision_level="watch")
        preview = preview_cr_repeat(
            event_key="e1",
            current_decision_level="urgent",
            seen_state=state,
            prior_state_snapshot_provided=True,
        )
        self.assertEqual(preview.status, "meaningful_escalation")

    def test_same_event_deescalation_is_deescalation(self):
        state = CRSeenEventState(event_key="e1", decision_level="urgent")
        preview = preview_cr_repeat(
            event_key="e1",
            current_decision_level="alert",
            seen_state=state,
            prior_state_snapshot_provided=True,
        )
        self.assertEqual(preview.status, "deescalation")

    def test_same_event_unknown_levels_is_same_event_repeat(self):
        state = CRSeenEventState(event_key="e1", decision_level=None)
        preview = preview_cr_repeat(
            event_key="e1",
            current_decision_level=None,
            seen_state=state,
            prior_state_snapshot_provided=True,
        )
        self.assertEqual(preview.status, "same_event_repeat")

    def test_seen_state_event_key_mismatch_is_new(self):
        state = CRSeenEventState(
            event_key="different-event",
            decision_level="urgent",
            score=90.0,
        )
        preview = preview_cr_repeat(
            event_key="e1",
            current_decision_level="alert",
            current_score=70.0,
            seen_state=state,
            prior_state_snapshot_provided=True,
        )
        self.assertEqual(preview.status, "new")
        self.assertEqual(
            preview.reason,
            "seen state event key does not match current event key",
        )
        self.assertIsNone(preview.previous_decision_level)
        self.assertIsNone(preview.previous_score)

    def test_seen_state_is_not_mutated(self):
        state = CRSeenEventState(
            event_key="e1",
            decision_level="watch",
            score=58.0,
            seen_at="2026-06-11T10:00:00+08:00",
            title="Topic",
            candidate_id="c1",
        )
        before = replace(state)
        preview_cr_repeat(
            event_key="e1",
            current_decision_level="alert",
            current_score=65.0,
            seen_state=state,
            prior_state_snapshot_provided=True,
        )
        self.assertEqual(state, before)


class TestBatchPreview(unittest.TestCase):
    def test_order_preserved(self):
        previews = preview_cr_repeats(
            (("e2", "urgent", 90.0), ("e1", "alert", 70.0)),
            seen_states={
                "e1": CRSeenEventState(event_key="e1", decision_level="watch"),
                "e2": CRSeenEventState(event_key="e2", decision_level="urgent"),
            },
        )
        self.assertEqual([p.event_key for p in previews], ["e2", "e1"])
        self.assertEqual(previews[0].status, "same_level_repeat")
        self.assertEqual(previews[1].status, "meaningful_escalation")

    def test_absent_keys_are_new_when_snapshot_exists(self):
        previews = preview_cr_repeats(
            (("e1", "alert", 70.0),),
            seen_states={},
        )
        self.assertEqual(previews[0].status, "new")

    def test_mismatched_seen_state_value_is_new(self):
        previews = preview_cr_repeats(
            (("e1", "alert", 70.0),),
            seen_states={
                "e1": CRSeenEventState(
                    event_key="different-event",
                    decision_level="urgent",
                )
            },
        )
        self.assertEqual(previews[0].status, "new")
        self.assertEqual(
            previews[0].reason,
            "seen state event key does not match current event key",
        )

    def test_all_not_evaluated_when_snapshot_is_none(self):
        previews = preview_cr_repeats(
            (("e1", "alert", 70.0), ("e2", "watch", 30.0)),
            seen_states=None,
        )
        self.assertEqual([p.status for p in previews], ["not_evaluated", "not_evaluated"])

    def test_seen_states_mapping_is_not_mutated(self):
        states = {
            "e1": CRSeenEventState(event_key="e1", decision_level="watch"),
        }
        before = dict(states)
        preview_cr_repeats((("e1", "alert", 70.0),), seen_states=states)
        self.assertEqual(states, before)


class TestPurityForbiddenBehavior(unittest.TestCase):
    def test_module_source_has_no_forbidden_io_network_env_or_transport(self):
        source = inspect.getsource(repeat_preview_module)
        forbidden_fragments = (
            "open(",
            "Path(",
            "os.environ",
            "requests",
            "httpx",
            "aiohttp",
            "urllib.request",
            "urlopen",
            "telegram_sink",
            "telegram_env",
            "dispatch_executor",
            "trendradar.cr.storage",
        )
        for fragment in forbidden_fragments:
            self.assertNotIn(fragment, source)


if __name__ == "__main__":
    unittest.main()
