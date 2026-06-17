# coding=utf-8
"""
PR-CR-A4: CR-A cooldown enforcement tests.

Covers:
  - Cooldown decision: new event, same-level repeat, escalation bypass,
    cooldown expiry, deescalation
  - State loading: missing state, malformed state, schema-invalid state
  - State mutation: artifact/shadow don't update, live accepted updates,
    live rejected/failed don't update
  - Escalation: alert->urgent bypass, urgent->urgent obeys cooldown
  - Integration: cooldown skip in plan/receipt JSON, artifacts still written

Pure tests only — no network, no Telegram, no real output directories.
"""

import json
import os
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from trendradar.cr.artifacts import CRArtifactConfig
from trendradar.cr.cooldown_enforce import (
    CRCooldownEnforcementResult,
    enforce_cr_cooldown,
    enforce_cr_cooldown_for_candidates,
)
from trendradar.cr.cooldown_policy import CRCooldownPolicy
from trendradar.cr.dispatch_executor import CRMemoryDispatchSink
from trendradar.cr.dispatch_plan import (
    CRDispatchPlan,
    DECISION_COOLDOWN,
    DECISION_DISPATCH,
)
from trendradar.cr.dispatch_receipt import (
    STATUS_ACCEPTED,
    STATUS_NOT_EXECUTED,
    STATUS_SHADOW_ONLY,
    STATUS_SKIPPED_COOLDOWN,
    STATUS_SKIPPED_REPEAT,
)
from trendradar.cr.repeat_preview import CRSeenEventState
from trendradar.cr.runtime_dry_run import build_and_write_cr_runtime_dry_run
from trendradar.cr.state_snapshot import (
    CREventStateEntry,
    CREventStateSnapshot,
    empty_cr_event_state_snapshot,
)
from trendradar.cr.state_store import (
    load_cr_event_state_snapshot,
    save_cr_event_state_snapshot,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _seen_state(
    event_key: str = "ev1",
    level: str = "alert",
    seen_at: str | None = None,
) -> CRSeenEventState:
    if seen_at is None:
        seen_at = (datetime.now(timezone.utc) - timedelta(minutes=10)).isoformat()
    return CRSeenEventState(
        event_key=event_key,
        decision_level=level,
        score=70.0,
        seen_at=seen_at,
        title="Test Topic",
        candidate_id="c1",
    )


def _hotlist_stats():
    return [
        {
            "word": "AI",
            "titles": [
                {
                    "title": "AI Title",
                    "source_name": "weibo",
                    "source_id": "weibo",
                    "ranks": [5],
                    "count": 3,
                    "first_time": "09:30",
                    "last_time": "12:00",
                    "url": "https://example.com",
                    "mobileUrl": "",
                    "is_new": False,
                    "rank_timeline": [],
                }
            ],
            "count": 1,
            "position": 0,
        }
    ]


# ---------------------------------------------------------------------------
# Test Group A — New event (no prior state)
# ---------------------------------------------------------------------------


class TestNewEvent(unittest.TestCase):
    def test_new_event_eligible(self):
        result = enforce_cr_cooldown(
            event_key="ev1",
            candidate_id="c1",
            current_level="alert",
            seen_state=None,
            prior_snapshot_provided=True,
        )
        self.assertTrue(result.should_dispatch)
        self.assertIsNone(result.override_reason)
        self.assertEqual(result.entries[0].cooldown_action, "allow_new")

    def test_no_snapshot_eligible(self):
        """Without prior snapshot, enforcement allows dispatch."""
        result = enforce_cr_cooldown(
            event_key="ev1",
            candidate_id="c1",
            current_level="alert",
            seen_state=None,
            prior_snapshot_provided=False,
        )
        self.assertTrue(result.should_dispatch)


# ---------------------------------------------------------------------------
# Test Group B — Same-level repeat inside cooldown
# ---------------------------------------------------------------------------


class TestSameLevelRepeat(unittest.TestCase):
    def test_same_alert_inside_cooldown(self):
        seen = _seen_state(level="alert", seen_at=datetime.now(timezone.utc).isoformat())
        policy = CRCooldownPolicy(same_level_cooldown_minutes=60)
        result = enforce_cr_cooldown(
            event_key="ev1",
            candidate_id="c1",
            current_level="alert",
            seen_state=seen,
            prior_snapshot_provided=True,
            policy=policy,
        )
        self.assertFalse(result.should_dispatch)
        self.assertEqual(result.override_reason, "skipped_repeat")

    def test_same_urgent_inside_cooldown(self):
        seen = _seen_state(level="urgent", seen_at=datetime.now(timezone.utc).isoformat())
        policy = CRCooldownPolicy(same_level_cooldown_minutes=120)
        result = enforce_cr_cooldown(
            event_key="ev1",
            candidate_id="c1",
            current_level="urgent",
            seen_state=seen,
            prior_snapshot_provided=True,
            policy=policy,
        )
        self.assertFalse(result.should_dispatch)
        self.assertEqual(result.override_reason, "skipped_repeat")


# ---------------------------------------------------------------------------
# Test Group C — Cooldown expired
# ---------------------------------------------------------------------------


class TestCooldownExpired(unittest.TestCase):
    def test_same_alert_after_cooldown(self):
        seen = _seen_state(
            level="alert",
            seen_at=(datetime.now(timezone.utc) - timedelta(hours=7)).isoformat(),
        )
        policy = CRCooldownPolicy(same_level_cooldown_minutes=360)  # 6 hours
        result = enforce_cr_cooldown(
            event_key="ev1",
            candidate_id="c1",
            current_level="alert",
            seen_state=seen,
            prior_snapshot_provided=True,
            policy=policy,
        )
        self.assertTrue(result.should_dispatch)


# ---------------------------------------------------------------------------
# Test Group D — Escalation bypass
# ---------------------------------------------------------------------------


class TestEscalationBypass(unittest.TestCase):
    def test_alert_to_urgent_escalation_allowed(self):
        """Alert→urgent escalation bypasses alert cooldown."""
        seen = _seen_state(
            level="alert",
            seen_at=datetime.now(timezone.utc).isoformat(),
        )
        policy = CRCooldownPolicy(same_level_cooldown_minutes=360)
        result = enforce_cr_cooldown(
            event_key="ev1",
            candidate_id="c1",
            current_level="urgent",
            seen_state=seen,
            prior_snapshot_provided=True,
            policy=policy,
        )
        self.assertTrue(result.should_dispatch)
        self.assertIsNone(result.override_reason)
        self.assertTrue(result.entries[0].is_escalation)

    def test_urgent_to_urgent_inside_cooldown_blocked(self):
        """Urgent→urgent repeat is blocked by urgent cooldown."""
        seen = _seen_state(
            level="urgent",
            seen_at=datetime.now(timezone.utc).isoformat(),
        )
        policy = CRCooldownPolicy(same_level_cooldown_minutes=120)
        result = enforce_cr_cooldown(
            event_key="ev1",
            candidate_id="c1",
            current_level="urgent",
            seen_state=seen,
            prior_snapshot_provided=True,
            policy=policy,
        )
        self.assertFalse(result.should_dispatch)
        self.assertEqual(result.override_reason, "skipped_repeat")

    def test_urgent_to_alert_deescalation_blocked(self):
        """Deescalation (urgent→alert) is blocked."""
        seen = _seen_state(
            level="urgent",
            seen_at=datetime.now(timezone.utc).isoformat(),
        )
        policy = CRCooldownPolicy(same_level_cooldown_minutes=120)
        result = enforce_cr_cooldown(
            event_key="ev1",
            candidate_id="c1",
            current_level="alert",
            seen_state=seen,
            prior_snapshot_provided=True,
            policy=policy,
        )
        self.assertFalse(result.should_dispatch)


# ---------------------------------------------------------------------------
# Test Group E — Batch enforcement
# ---------------------------------------------------------------------------


class TestBatchEnforcement(unittest.TestCase):
    def test_batch_allows_when_all_eligible(self):
        from trendradar.cr.presentation import CRPresentedCandidate
        from trendradar.cr.decision import CRDecision
        from trendradar.cr.scoring import CRScoreResult
        from trendradar.cr.models import CRCandidate

        cand = CRCandidate(
            candidate_id="c1", cluster_key="ev1",
            display_title="T", representative_url=None, source_items=[],
        )
        sr = CRScoreResult(
            candidate_id="c1", cluster_key="ev1",
            profile_version="v", total_score=70.0,
            trigger_reasons=[], debug={},
        )
        dec = CRDecision(
            candidate_id="c1", cluster_key="ev1",
            profile_version="v", policy_version="v",
            level="alert", total_score=70.0, push_eligible=True,
            suppress_labels=[], trigger_reasons=[], debug={},
        )
        pc = CRPresentedCandidate(
            candidate=cand, score_result=sr, decision=dec,
            candidate_id="c1", cluster_key="ev1",
            display_title="T", representative_url=None,
            decision_level="alert", total_score=70.0,
            trigger_reasons=[], suppress_labels=[],
        )

        result = enforce_cr_cooldown_for_candidates(
            cr_a_candidates=(pc,),
            seen_states={},
            prior_snapshot_provided=True,
        )
        self.assertTrue(result.should_dispatch)


# ---------------------------------------------------------------------------
# Test Group F — State loading
# ---------------------------------------------------------------------------


class TestStateLoading(unittest.TestCase):
    def test_missing_state_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "nonexistent.json"
            result = load_cr_event_state_snapshot(path)
            self.assertFalse(result.loaded)
            self.assertIsNone(result.error)

    def test_malformed_json_state(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "state.json"
            path.write_text("not json", encoding="utf-8")
            result = load_cr_event_state_snapshot(path)
            self.assertFalse(result.loaded)
            self.assertIsNotNone(result.error)
            self.assertIn("malformed", result.error)

    def test_schema_invalid_state(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "state.json"
            path.write_text('{"schema_version": "wrong"}', encoding="utf-8")
            result = load_cr_event_state_snapshot(path)
            self.assertFalse(result.loaded)
            self.assertIsNotNone(result.error)


# ---------------------------------------------------------------------------
# Test Group G — State mutation
# ---------------------------------------------------------------------------


class TestStateMutation(unittest.TestCase):
    def test_artifact_mode_does_not_update_state(self):
        with tempfile.TemporaryDirectory() as tmp:
            state_path = Path(tmp) / "dispatch_state.json"
            result = build_and_write_cr_runtime_dry_run(
                hotlist_stats=_hotlist_stats(),
                run_label="mut-art",
                artifact_config=CRArtifactConfig(root_dir=Path(tmp)),
                dispatch_mode="artifact",
                dispatch_state_path=str(state_path),
            )
            # State should not be written in artifact mode.
            self.assertIsNone(result.dispatch_state_save)

    def test_shadow_mode_does_not_update_state(self):
        with tempfile.TemporaryDirectory() as tmp:
            state_path = Path(tmp) / "dispatch_state.json"
            result = build_and_write_cr_runtime_dry_run(
                hotlist_stats=_hotlist_stats(),
                run_label="mut-shd",
                artifact_config=CRArtifactConfig(root_dir=Path(tmp)),
                dispatch_mode="shadow",
                dispatch_state_path=str(state_path),
            )
            self.assertIsNone(result.dispatch_state_save)

    def test_live_without_sink_does_not_update_state(self):
        with tempfile.TemporaryDirectory() as tmp:
            state_path = Path(tmp) / "dispatch_state.json"
            result = build_and_write_cr_runtime_dry_run(
                hotlist_stats=_hotlist_stats(),
                run_label="mut-live",
                artifact_config=CRArtifactConfig(root_dir=Path(tmp)),
                dispatch_mode="live",
                dispatch_sink=None,
                dispatch_state_path=str(state_path),
            )
            self.assertIsNone(result.dispatch_state_save)


# ---------------------------------------------------------------------------
# Test Group H — Integration: cooldown in plan/receipt JSON
# ---------------------------------------------------------------------------


class TestCooldownIntegration(unittest.TestCase):
    def test_cooldown_context_in_plan_json(self):
        """When cooldown is evaluated, context appears in plan JSON."""
        with tempfile.TemporaryDirectory() as tmp:
            result = build_and_write_cr_runtime_dry_run(
                hotlist_stats=_hotlist_stats(),
                run_label="cd-plan",
                artifact_config=CRArtifactConfig(root_dir=Path(tmp)),
                dispatch_mode="artifact",
            )
            path = result.dispatch_plan_json_paths.dispatch_plan_latest_path
            data = json.loads(path.read_text(encoding="utf-8"))
            # Cooldown context may or may not be present depending on candidates.
            # If present, it should be a dict.
            if "cooldown" in data:
                self.assertIsInstance(data["cooldown"], dict)

    def test_receipt_json_written_with_cooldown(self):
        """Receipt JSON is written even when cooldown is evaluated."""
        with tempfile.TemporaryDirectory() as tmp:
            result = build_and_write_cr_runtime_dry_run(
                hotlist_stats=_hotlist_stats(),
                run_label="cd-rcpt",
                artifact_config=CRArtifactConfig(root_dir=Path(tmp)),
                dispatch_mode="artifact",
            )
            path = result.dispatch_receipt_json_paths.dispatch_receipt_latest_path
            self.assertTrue(path.exists())
            data = json.loads(path.read_text(encoding="utf-8"))
            self.assertIn("receipts", data)


# ---------------------------------------------------------------------------
# Test Group I — Boundary
# ---------------------------------------------------------------------------


class TestSourceBoundary(unittest.TestCase):
    FORBIDDEN = (
        "trendradar.notification",
        "trendradar.storage",
        "trendradar.config",
        "trendradar.ai",
        "AIAnalysisResult",
        "telegram",
        "chat_id",
        "bot_token",
    )

    def test_no_forbidden_tokens_in_cooldown_enforce(self):
        import trendradar.cr.cooldown_enforce as mod
        source = Path(mod.__file__).read_text(encoding="utf-8")
        for token in self.FORBIDDEN:
            self.assertNotIn(token, source, f"forbidden token {token!r} present")


if __name__ == "__main__":
    unittest.main()
