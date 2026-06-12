# coding=utf-8
"""
Tests for the CR-A cooldown policy decision layer (PR10d).

The module under test is pure and preview-only: it computes what a cooldown
policy *would* decide for an event given a repeat preview. It does not
suppress, persist, fetch, send, or read any clock.
"""

import inspect
import unittest

from trendradar.cr.cooldown_policy import (
    CRCooldownDecision,
    CRCooldownPolicy,
    decide_cr_cooldown,
    decide_cr_cooldowns,
)
import trendradar.cr.cooldown_policy as cooldown_policy_module
from trendradar.cr.repeat_preview import CRRepeatPreview


def _preview(
    status: str,
    *,
    event_key: str = "e1",
    current_level: str | None = None,
    previous_level: str | None = None,
    current_score: float | None = None,
    previous_score: float | None = None,
) -> CRRepeatPreview:
    return CRRepeatPreview(
        event_key=event_key,
        status=status,
        reason=f"test::{status}",
        current_decision_level=current_level,
        previous_decision_level=previous_level,
        current_score=current_score,
        previous_score=previous_score,
    )


class TestPolicyDefaults(unittest.TestCase):
    def test_same_level_cooldown_default_is_60_minutes(self):
        self.assertEqual(CRCooldownPolicy().same_level_cooldown_minutes, 60)

    def test_meaningful_escalation_allowed_by_default(self):
        self.assertTrue(CRCooldownPolicy().allow_meaningful_escalation)

    def test_new_events_allowed_by_default(self):
        self.assertTrue(CRCooldownPolicy().allow_new_events)

    def test_deescalation_not_allowed_by_default(self):
        self.assertFalse(CRCooldownPolicy().allow_deescalation)


class TestSingleDecision(unittest.TestCase):
    def test_no_repeat_preview_is_not_evaluated(self):
        decision = decide_cr_cooldown(event_key="e1", repeat_preview=None)
        self.assertEqual(decision.action, "not_evaluated")
        self.assertEqual(decision.reason, "no repeat preview supplied")
        self.assertEqual(decision.event_key, "e1")
        self.assertIsNone(decision.repeat_status)

    def test_repeat_status_not_evaluated_is_not_evaluated(self):
        decision = decide_cr_cooldown(
            event_key="e1",
            repeat_preview=_preview("not_evaluated"),
        )
        self.assertEqual(decision.action, "not_evaluated")
        self.assertEqual(decision.repeat_status, "not_evaluated")

    def test_new_is_allow_new(self):
        decision = decide_cr_cooldown(
            event_key="e1",
            repeat_preview=_preview("new", current_level="alert"),
        )
        self.assertEqual(decision.action, "allow_new")
        self.assertEqual(decision.repeat_status, "new")
        self.assertIsNone(decision.cooldown_minutes)

    def test_same_level_repeat_is_cooldown(self):
        decision = decide_cr_cooldown(
            event_key="e1",
            repeat_preview=_preview(
                "same_level_repeat",
                current_level="alert",
                previous_level="alert",
            ),
        )
        self.assertEqual(decision.action, "cooldown")
        self.assertEqual(decision.cooldown_minutes, 60)

    def test_same_event_repeat_is_cooldown(self):
        decision = decide_cr_cooldown(
            event_key="e1",
            repeat_preview=_preview("same_event_repeat"),
        )
        self.assertEqual(decision.action, "cooldown")
        self.assertEqual(decision.cooldown_minutes, 60)

    def test_meaningful_escalation_is_allow_escalation(self):
        decision = decide_cr_cooldown(
            event_key="e1",
            repeat_preview=_preview(
                "meaningful_escalation",
                previous_level="watch",
                current_level="urgent",
            ),
        )
        self.assertEqual(decision.action, "allow_escalation")
        self.assertIsNone(decision.cooldown_minutes)

    def test_meaningful_escalation_with_policy_disabled_is_cooldown(self):
        policy = CRCooldownPolicy(allow_meaningful_escalation=False)
        decision = decide_cr_cooldown(
            event_key="e1",
            repeat_preview=_preview("meaningful_escalation"),
            policy=policy,
        )
        self.assertEqual(decision.action, "cooldown")
        self.assertEqual(decision.cooldown_minutes, 60)

    def test_deescalation_is_cooldown_by_default(self):
        decision = decide_cr_cooldown(
            event_key="e1",
            repeat_preview=_preview("deescalation"),
        )
        self.assertEqual(decision.action, "cooldown")
        self.assertEqual(decision.cooldown_minutes, 60)

    def test_deescalation_with_policy_enabled_is_allow(self):
        policy = CRCooldownPolicy(allow_deescalation=True)
        decision = decide_cr_cooldown(
            event_key="e1",
            repeat_preview=_preview("deescalation"),
            policy=policy,
        )
        self.assertEqual(decision.action, "allow")
        self.assertIsNone(decision.cooldown_minutes)

    def test_new_with_policy_disabled_is_cooldown(self):
        policy = CRCooldownPolicy(allow_new_events=False)
        decision = decide_cr_cooldown(
            event_key="e1",
            repeat_preview=_preview("new"),
            policy=policy,
        )
        self.assertEqual(decision.action, "cooldown")
        self.assertEqual(decision.cooldown_minutes, 60)

    def test_mismatched_event_key_fails_closed_to_not_evaluated(self):
        # A preview built for a different event must never yield a verdict.
        for status in (
            "new",
            "same_level_repeat",
            "same_event_repeat",
            "meaningful_escalation",
            "deescalation",
        ):
            with self.subTest(status=status):
                decision = decide_cr_cooldown(
                    event_key="e1",
                    repeat_preview=_preview(
                        status,
                        event_key="different-event",
                        previous_level="watch",
                        current_level="urgent",
                    ),
                    # Even a permissive policy must not flip the verdict.
                    policy=CRCooldownPolicy(allow_deescalation=True),
                )
                self.assertEqual(decision.action, "not_evaluated")
                self.assertEqual(
                    decision.reason,
                    "repeat preview event key does not match current event key",
                )
                self.assertEqual(decision.event_key, "e1")
                self.assertNotIn(
                    decision.action,
                    ("cooldown", "allow", "allow_escalation", "allow_new"),
                )
                # Evidence from the preview is preserved for audit.
                self.assertEqual(decision.repeat_status, status)

    def test_evidence_is_carried_through(self):
        decision = decide_cr_cooldown(
            event_key="e1",
            repeat_preview=_preview(
                "same_level_repeat",
                current_level="alert",
                previous_level="alert",
                current_score=67.0,
                previous_score=65.0,
            ),
        )
        self.assertEqual(decision.current_decision_level, "alert")
        self.assertEqual(decision.previous_decision_level, "alert")
        self.assertEqual(decision.current_score, 67.0)
        self.assertEqual(decision.previous_score, 65.0)


class TestBatchDecision(unittest.TestCase):
    def test_order_preserved(self):
        previews = (
            _preview("new", event_key="e2"),
            _preview("same_level_repeat", event_key="e1"),
            _preview("meaningful_escalation", event_key="e3"),
        )
        decisions = decide_cr_cooldowns(previews)
        self.assertEqual(
            [d.event_key for d in decisions], ["e2", "e1", "e3"]
        )
        self.assertEqual(
            [d.action for d in decisions],
            ["allow_new", "cooldown", "allow_escalation"],
        )

    def test_returns_tuple(self):
        decisions = decide_cr_cooldowns((_preview("new"),))
        self.assertIsInstance(decisions, tuple)

    def test_no_mutation_of_inputs(self):
        previews = (
            _preview("new", event_key="e1"),
            _preview("deescalation", event_key="e2"),
        )
        before = tuple(previews)
        decide_cr_cooldowns(previews)
        self.assertEqual(previews, before)
        # CRRepeatPreview is frozen; identity is preserved too.
        self.assertIs(previews[0], before[0])

    def test_empty_batch_is_empty_tuple(self):
        self.assertEqual(decide_cr_cooldowns(()), ())


class TestPurityForbiddenBehavior(unittest.TestCase):
    def test_module_source_has_no_forbidden_io_network_env_clock_or_transport(
        self,
    ):
        source = inspect.getsource(cooldown_policy_module)
        forbidden_fragments = (
            "open(",
            "Path(",
            "os.environ",
            "datetime.now",
            "time.time",
            "requests",
            "httpx",
            "aiohttp",
            "urllib.request",
            "urlopen",
            # Runtime / transport / state / config imports must be absent.
            # These are checked as import paths so prose in the module
            # docstring (which may mention "config.yaml", "Telegram", ...)
            # does not trip the guard.
            "telegram_sink",
            "telegram_env",
            "dispatch_executor",
            "dispatch_plan",
            "runtime_dry_run",
            "state_store",
            "import config",
            "from config",
            "trendradar.config",
        )
        for fragment in forbidden_fragments:
            self.assertNotIn(fragment, source)

    def test_decision_is_a_frozen_dataclass(self):
        decision = decide_cr_cooldown(
            event_key="e1", repeat_preview=_preview("new")
        )
        self.assertIsInstance(decision, CRCooldownDecision)
        with self.assertRaises(Exception):
            decision.action = "cooldown"  # type: ignore[misc]


if __name__ == "__main__":
    unittest.main()
