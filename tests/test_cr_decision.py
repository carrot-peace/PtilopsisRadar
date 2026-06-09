# coding=utf-8
"""
PR9e: CR decision policy tests.

Covers:
  A. Policy defaults
  B. Level mapping
  C. Suppress veto
  D. Push flags
  E. Custom policy
  F. Trigger reasons
  G. Batch helper
  H. High-score suppressed helper
  I. No runtime behavior
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from trendradar.cr.decision import (
    CRDecision,
    CRDecisionLevel,
    CRDecisionPolicy,
    DEFAULT_CR_DECISION_POLICY,
    DECISION_ALERT,
    DECISION_SUPPRESS,
    DECISION_URGENT,
    DECISION_WATCH,
    apply_cr_decision,
    count_high_score_suppressed,
    decide_cr_candidates,
)
from trendradar.cr.scoring import CRComponentScore, CRScoreResult


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_score_result(
    *,
    candidate_id="c1",
    cluster_key="k1",
    total_score=0.0,
    trigger_reasons: list[str] | None = None,
    profile_version="cr-score-v0.1",
) -> CRScoreResult:
    """Build a minimal CRScoreResult for decision tests."""
    return CRScoreResult(
        candidate_id=candidate_id,
        cluster_key=cluster_key,
        profile_version=profile_version,
        total_score=total_score,
        trigger_reasons=list(trigger_reasons) if trigger_reasons else [],
    )


# ===========================================================================
# A. Policy defaults
# ===========================================================================


class TestPolicyDefaults(unittest.TestCase):

    def test_policy_version(self):
        self.assertEqual(DEFAULT_CR_DECISION_POLICY.policy_version, "cr-decision-v0.1")

    def test_alert_threshold(self):
        self.assertAlmostEqual(DEFAULT_CR_DECISION_POLICY.alert_threshold, 60.0)

    def test_urgent_threshold(self):
        self.assertAlmostEqual(DEFAULT_CR_DECISION_POLICY.urgent_threshold, 80.0)

    def test_suppress_overrides_all(self):
        self.assertTrue(DEFAULT_CR_DECISION_POLICY.suppress_overrides_all)

    def test_alert_push_eligible(self):
        self.assertTrue(DEFAULT_CR_DECISION_POLICY.alert_push_eligible)

    def test_urgent_push_eligible(self):
        self.assertTrue(DEFAULT_CR_DECISION_POLICY.urgent_push_eligible)

    def test_urgent_bypasses_quiet(self):
        self.assertTrue(DEFAULT_CR_DECISION_POLICY.urgent_bypasses_quiet)

    def test_watch_push_eligible(self):
        self.assertFalse(DEFAULT_CR_DECISION_POLICY.watch_push_eligible)

    def test_suppress_push_eligible(self):
        self.assertFalse(DEFAULT_CR_DECISION_POLICY.suppress_push_eligible)

    def test_frozen(self):
        with self.assertRaises(AttributeError):
            DEFAULT_CR_DECISION_POLICY.alert_threshold = 50.0


# ===========================================================================
# B. Level mapping
# ===========================================================================


class TestLevelMapping(unittest.TestCase):

    def test_score_zero_is_watch(self):
        sr = _make_score_result(total_score=0.0)
        d = apply_cr_decision(sr)
        self.assertEqual(d.level, DECISION_WATCH)

    def test_score_below_alert_is_watch(self):
        sr = _make_score_result(total_score=59.999)
        d = apply_cr_decision(sr)
        self.assertEqual(d.level, DECISION_WATCH)

    def test_score_at_alert_is_alert(self):
        sr = _make_score_result(total_score=60.0)
        d = apply_cr_decision(sr)
        self.assertEqual(d.level, DECISION_ALERT)

    def test_score_below_urgent_is_alert(self):
        sr = _make_score_result(total_score=79.999)
        d = apply_cr_decision(sr)
        self.assertEqual(d.level, DECISION_ALERT)

    def test_score_at_urgent_is_urgent(self):
        sr = _make_score_result(total_score=80.0)
        d = apply_cr_decision(sr)
        self.assertEqual(d.level, DECISION_URGENT)

    def test_score_above_urgent_is_urgent(self):
        sr = _make_score_result(total_score=100.0)
        d = apply_cr_decision(sr)
        self.assertEqual(d.level, DECISION_URGENT)


# ===========================================================================
# C. Suppress veto
# ===========================================================================


class TestSuppressVeto(unittest.TestCase):

    def test_high_score_with_labels_is_suppress(self):
        sr = _make_score_result(total_score=100.0)
        d = apply_cr_decision(sr, suppress_labels=["low_quality"])
        self.assertEqual(d.level, DECISION_SUPPRESS)

    def test_suppress_push_eligible_false(self):
        sr = _make_score_result(total_score=100.0)
        d = apply_cr_decision(sr, suppress_labels=["x"])
        self.assertFalse(d.push_eligible)

    def test_suppress_bypasses_quiet_false(self):
        sr = _make_score_result(total_score=100.0)
        d = apply_cr_decision(sr, suppress_labels=["x"])
        self.assertFalse(d.bypasses_quiet)

    def test_suppress_labels_copied(self):
        sr = _make_score_result(total_score=100.0)
        labels = ["a", "b"]
        d = apply_cr_decision(sr, suppress_labels=labels)
        self.assertEqual(d.suppress_labels, ["a", "b"])
        # Mutation isolation.
        labels.append("c")
        self.assertEqual(d.suppress_labels, ["a", "b"])

    def test_suppress_reason_included(self):
        sr = _make_score_result(total_score=100.0, trigger_reasons=["rank_improvement=21.0"])
        d = apply_cr_decision(sr, suppress_labels=["x"])
        self.assertIn("suppress_label", d.trigger_reasons)

    def test_score_result_retained(self):
        sr = _make_score_result(total_score=100.0)
        d = apply_cr_decision(sr, suppress_labels=["x"])
        self.assertIs(d.score_result, sr)

    def test_no_labels_no_suppress(self):
        sr = _make_score_result(total_score=100.0)
        d = apply_cr_decision(sr, suppress_labels=None)
        self.assertEqual(d.level, DECISION_URGENT)

    def test_empty_labels_no_suppress(self):
        sr = _make_score_result(total_score=100.0)
        d = apply_cr_decision(sr, suppress_labels=[])
        self.assertEqual(d.level, DECISION_URGENT)


# ===========================================================================
# D. Push flags
# ===========================================================================


class TestPushFlags(unittest.TestCase):

    def test_watch_push_eligible_false(self):
        sr = _make_score_result(total_score=0.0)
        d = apply_cr_decision(sr)
        self.assertEqual(d.level, DECISION_WATCH)
        self.assertFalse(d.push_eligible)
        self.assertFalse(d.bypasses_quiet)

    def test_alert_push_eligible_true_bypasses_quiet_false(self):
        sr = _make_score_result(total_score=70.0)
        d = apply_cr_decision(sr)
        self.assertEqual(d.level, DECISION_ALERT)
        self.assertTrue(d.push_eligible)
        self.assertFalse(d.bypasses_quiet)

    def test_urgent_push_eligible_true_bypasses_quiet_true(self):
        sr = _make_score_result(total_score=90.0)
        d = apply_cr_decision(sr)
        self.assertEqual(d.level, DECISION_URGENT)
        self.assertTrue(d.push_eligible)
        self.assertTrue(d.bypasses_quiet)

    def test_suppress_push_eligible_false(self):
        sr = _make_score_result(total_score=100.0)
        d = apply_cr_decision(sr, suppress_labels=["x"])
        self.assertEqual(d.level, DECISION_SUPPRESS)
        self.assertFalse(d.push_eligible)
        self.assertFalse(d.bypasses_quiet)


# ===========================================================================
# E. Custom policy
# ===========================================================================


class TestCustomPolicy(unittest.TestCase):

    def test_custom_alert_threshold(self):
        policy = CRDecisionPolicy(alert_threshold=50.0)
        sr = _make_score_result(total_score=55.0)
        d = apply_cr_decision(sr, policy=policy)
        self.assertEqual(d.level, DECISION_ALERT)

    def test_custom_urgent_threshold(self):
        policy = CRDecisionPolicy(urgent_threshold=90.0)
        sr = _make_score_result(total_score=85.0)
        d = apply_cr_decision(sr, policy=policy)
        self.assertEqual(d.level, DECISION_ALERT)

    def test_urgent_bypasses_quiet_false(self):
        policy = CRDecisionPolicy(urgent_bypasses_quiet=False)
        sr = _make_score_result(total_score=90.0)
        d = apply_cr_decision(sr, policy=policy)
        self.assertEqual(d.level, DECISION_URGENT)
        self.assertTrue(d.push_eligible)
        self.assertFalse(d.bypasses_quiet)

    def test_watch_push_eligible_true(self):
        policy = CRDecisionPolicy(watch_push_eligible=True)
        sr = _make_score_result(total_score=10.0)
        d = apply_cr_decision(sr, policy=policy)
        self.assertEqual(d.level, DECISION_WATCH)
        self.assertTrue(d.push_eligible)

    def test_suppress_overrides_all_false(self):
        """With suppress_overrides_all=False, high score still urgent despite labels."""
        policy = CRDecisionPolicy(suppress_overrides_all=False)
        sr = _make_score_result(total_score=100.0)
        d = apply_cr_decision(sr, policy=policy, suppress_labels=["low_quality"])
        self.assertEqual(d.level, DECISION_URGENT)
        # Labels still recorded even though not suppress.
        self.assertEqual(d.suppress_labels, ["low_quality"])

    def test_custom_policy_version_in_decision(self):
        policy = CRDecisionPolicy(policy_version="custom-v2")
        sr = _make_score_result(total_score=10.0)
        d = apply_cr_decision(sr, policy=policy)
        self.assertEqual(d.policy_version, "custom-v2")

    def test_debug_contains_thresholds(self):
        policy = CRDecisionPolicy(alert_threshold=40.0, urgent_threshold=70.0)
        sr = _make_score_result(total_score=10.0)
        d = apply_cr_decision(sr, policy=policy)
        self.assertAlmostEqual(d.debug["alert_threshold"], 40.0)
        self.assertAlmostEqual(d.debug["urgent_threshold"], 70.0)
        self.assertTrue(d.debug["suppress_overrides_all"])


# ===========================================================================
# F. Trigger reasons
# ===========================================================================


class TestTriggerReasons(unittest.TestCase):

    def test_reasons_copied_from_score_result(self):
        sr = _make_score_result(
            total_score=10.0,
            trigger_reasons=["rank_movement=21.0", "new_burst=12.0"],
        )
        d = apply_cr_decision(sr)
        self.assertEqual(d.trigger_reasons, ["rank_movement=21.0", "new_burst=12.0"])

    def test_suppress_reason_added(self):
        sr = _make_score_result(total_score=100.0, trigger_reasons=["a"])
        d = apply_cr_decision(sr, suppress_labels=["x"])
        self.assertEqual(d.trigger_reasons, ["a", "suppress_label"])

    def test_duplicate_reasons_deduped(self):
        sr = _make_score_result(
            total_score=10.0,
            trigger_reasons=["a", "b", "a", "c", "b"],
        )
        d = apply_cr_decision(sr)
        self.assertEqual(d.trigger_reasons, ["a", "b", "c"])

    def test_suppress_label_deduped(self):
        """If 'suppress_label' already in score_result reasons, don't duplicate."""
        sr = _make_score_result(
            total_score=100.0,
            trigger_reasons=["suppress_label", "a"],
        )
        d = apply_cr_decision(sr, suppress_labels=["x"])
        self.assertEqual(d.trigger_reasons, ["suppress_label", "a"])

    def test_no_mutable_aliasing(self):
        """Input list is copied; mutating score_result.trigger_reasons after
        apply_cr_decision does not affect the decision."""
        sr = _make_score_result(total_score=10.0, trigger_reasons=["a"])
        d = apply_cr_decision(sr)
        sr.trigger_reasons.append("b")
        self.assertEqual(d.trigger_reasons, ["a"])


# ===========================================================================
# G. Batch helper
# ===========================================================================


class TestBatchHelper(unittest.TestCase):

    def test_returns_same_length(self):
        srs = [
            _make_score_result(candidate_id="a", total_score=10.0),
            _make_score_result(candidate_id="b", total_score=70.0),
            _make_score_result(candidate_id="c", total_score=90.0),
        ]
        decisions = decide_cr_candidates(srs)
        self.assertEqual(len(decisions), 3)

    def test_preserves_input_order(self):
        srs = [
            _make_score_result(candidate_id="z", total_score=10.0),
            _make_score_result(candidate_id="a", total_score=90.0),
            _make_score_result(candidate_id="m", total_score=70.0),
        ]
        decisions = decide_cr_candidates(srs)
        self.assertEqual([d.candidate_id for d in decisions], ["z", "a", "m"])

    def test_suppress_labels_applied(self):
        srs = [
            _make_score_result(candidate_id="a", total_score=100.0),
            _make_score_result(candidate_id="b", total_score=100.0),
        ]
        labels_map = {"a": ["low_quality"]}
        decisions = decide_cr_candidates(srs, suppress_labels_by_candidate_id=labels_map)
        self.assertEqual(decisions[0].level, DECISION_SUPPRESS)
        self.assertEqual(decisions[1].level, DECISION_URGENT)

    def test_candidates_without_labels_unaffected(self):
        srs = [
            _make_score_result(candidate_id="a", total_score=90.0),
        ]
        decisions = decide_cr_candidates(srs, suppress_labels_by_candidate_id={})
        self.assertEqual(decisions[0].level, DECISION_URGENT)

    def test_no_labels_map(self):
        srs = [_make_score_result(candidate_id="a", total_score=70.0)]
        decisions = decide_cr_candidates(srs, suppress_labels_by_candidate_id=None)
        self.assertEqual(decisions[0].level, DECISION_ALERT)

    def test_custom_policy_propagates(self):
        policy = CRDecisionPolicy(alert_threshold=50.0)
        srs = [_make_score_result(candidate_id="a", total_score=55.0)]
        decisions = decide_cr_candidates(srs, policy=policy)
        self.assertEqual(decisions[0].level, DECISION_ALERT)


# ===========================================================================
# H. High-score suppressed helper
# ===========================================================================


class TestHighScoreSuppressed(unittest.TestCase):

    def test_suppress_score_80_counted(self):
        d = CRDecision(
            candidate_id="a", cluster_key="k", profile_version="p",
            policy_version="pol", level=DECISION_SUPPRESS, total_score=80.0,
        )
        self.assertEqual(count_high_score_suppressed([d]), 1)

    def test_suppress_score_below_not_counted(self):
        d = CRDecision(
            candidate_id="a", cluster_key="k", profile_version="p",
            policy_version="pol", level=DECISION_SUPPRESS, total_score=79.999,
        )
        self.assertEqual(count_high_score_suppressed([d]), 0)

    def test_alert_not_counted(self):
        d = CRDecision(
            candidate_id="a", cluster_key="k", profile_version="p",
            policy_version="pol", level=DECISION_ALERT, total_score=90.0,
        )
        self.assertEqual(count_high_score_suppressed([d]), 0)

    def test_urgent_not_counted(self):
        d = CRDecision(
            candidate_id="a", cluster_key="k", profile_version="p",
            policy_version="pol", level=DECISION_URGENT, total_score=90.0,
        )
        self.assertEqual(count_high_score_suppressed([d]), 0)

    def test_custom_urgent_threshold(self):
        d = CRDecision(
            candidate_id="a", cluster_key="k", profile_version="p",
            policy_version="pol", level=DECISION_SUPPRESS, total_score=70.0,
        )
        self.assertEqual(count_high_score_suppressed([d], urgent_threshold=70.0), 1)
        self.assertEqual(count_high_score_suppressed([d], urgent_threshold=70.001), 0)

    def test_mixed_decisions(self):
        decisions = [
            CRDecision(
                candidate_id="a", cluster_key="k", profile_version="p",
                policy_version="pol", level=DECISION_SUPPRESS, total_score=90.0,
            ),
            CRDecision(
                candidate_id="b", cluster_key="k", profile_version="p",
                policy_version="pol", level=DECISION_SUPPRESS, total_score=50.0,
            ),
            CRDecision(
                candidate_id="c", cluster_key="k", profile_version="p",
                policy_version="pol", level=DECISION_URGENT, total_score=95.0,
            ),
        ]
        self.assertEqual(count_high_score_suppressed(decisions), 1)


# ===========================================================================
# I. No runtime behavior
# ===========================================================================


class TestNoRuntimeBehavior(unittest.TestCase):
    """Assert that CRDecision has no delivery / runtime mutation fields."""

    FORBIDDEN_FIELDS = [
        "sent",
        "delivered",
        "telegram_message_id",
        "cooldown_applied",
        "dedupe_applied",
        "archived",
    ]

    def test_no_forbidden_fields_on_decision(self):
        """CRDecision must not have any runtime mutation fields."""
        d = CRDecision(
            candidate_id="test", cluster_key="test",
            profile_version="p", policy_version="pol",
        )
        for field_name in self.FORBIDDEN_FIELDS:
            self.assertFalse(
                hasattr(d, field_name),
                f"CRDecision must not have field '{field_name}'",
            )

    def test_no_forbidden_fields_on_dataclass(self):
        """CRDecision dataclass fields must not include forbidden fields."""
        field_names = {f.name for f in CRDecision.__dataclass_fields__.values()}
        for name in self.FORBIDDEN_FIELDS:
            self.assertNotIn(name, field_names, f"CRDecision has forbidden field '{name}'")

    def test_decision_module_no_telegram_import(self):
        """decision.py must not import telegram / report / storage modules."""
        import trendradar.cr.decision as mod
        source_file = mod.__file__
        with open(source_file, "r") as f:
            source = f.read()
        for forbidden in ["telegram", "report", "archive", "storage", "config", "cooldown", "dedupe"]:
            # Check as import statements, not substrings in comments/strings.
            # Simple heuristic: no 'import <forbidden>' or 'from <forbidden>'.
            import_pattern = f"import {forbidden}"
            from_pattern = f"from {forbidden}"
            self.assertNotIn(
                import_pattern, source,
                f"decision.py contains '{import_pattern}'",
            )
            self.assertNotIn(
                from_pattern, source,
                f"decision.py contains '{from_pattern}'",
            )


# ===========================================================================
# Run
# ===========================================================================

if __name__ == "__main__":
    unittest.main()
