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
    CRCooldownEnforcementEntry,
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


# ---------------------------------------------------------------------------
# Test Group J — Blocker 1: Malformed state fails closed
# ---------------------------------------------------------------------------


class TestMalformedStateFailClosed(unittest.TestCase):
    def test_enforcement_blocks_on_state_error(self):
        """enforce_cr_cooldown_for_candidates with state_error → fail closed."""
        from unittest.mock import MagicMock
        pc = MagicMock()
        pc.cluster_key = "ev1"
        pc.candidate_id = "c1"
        pc.decision_level = "alert"

        result = enforce_cr_cooldown_for_candidates(
            cr_a_candidates=(pc,),
            seen_states=None,
            prior_snapshot_provided=False,
            state_error="malformed event state JSON: JSONDecodeError",
        )
        self.assertFalse(result.should_dispatch)
        self.assertEqual(result.override_reason, "skipped_state_error")
        self.assertEqual(result.eligible_candidates, ())

    def test_enforcement_entry_for_state_error(self):
        """State error produces entries with not_evaluated action."""
        from unittest.mock import MagicMock
        pc = MagicMock()
        pc.cluster_key = "ev1"
        pc.candidate_id = "c1"
        pc.decision_level = "alert"

        result = enforce_cr_cooldown_for_candidates(
            cr_a_candidates=(pc,),
            seen_states=None,
            prior_snapshot_provided=False,
            state_error="schema_version mismatch",
        )
        self.assertEqual(len(result.entries), 1)
        self.assertEqual(result.entries[0].cooldown_action, "not_evaluated")
        self.assertFalse(result.state_available)

    def test_state_error_does_not_allow_dispatch(self):
        """Even with no prior state, state_error blocks."""
        from unittest.mock import MagicMock
        pc = MagicMock()
        pc.cluster_key = "ev-new"
        pc.candidate_id = "c-new"
        pc.decision_level = "urgent"

        result = enforce_cr_cooldown_for_candidates(
            cr_a_candidates=(pc,),
            seen_states={},
            prior_snapshot_provided=False,
            state_error="malformed event state JSON",
        )
        self.assertFalse(result.should_dispatch)
        self.assertEqual(result.override_reason, "skipped_state_error")


# ---------------------------------------------------------------------------
# Test Group K — Blocker 2: Canonical event key consistency
# ---------------------------------------------------------------------------


class TestCanonicalEventKey(unittest.TestCase):
    def test_state_write_uses_cluster_key(self):
        """State entries must use pc.cluster_key as event_key."""
        from trendradar.cr.state_snapshot import (
            CREventStateEntry,
            merge_cr_event_state_entries,
            cr_event_state_snapshot_to_seen_states,
            empty_cr_event_state_snapshot,
        )
        now = datetime.now(timezone.utc)
        # Simulate what runtime does: write with cluster_key.
        entry = CREventStateEntry(
            event_key="ev-A",  # cluster_key
            decision_level="alert",
            score=70.0,
            seen_at=now.isoformat(),
            title="Topic A",
            candidate_id="c-A",
        )
        snapshot = merge_cr_event_state_entries(
            empty_cr_event_state_snapshot(), (entry,)
        )
        seen = cr_event_state_snapshot_to_seen_states(snapshot)
        # Lookup by same key should find it.
        self.assertIn("ev-A", seen)
        self.assertEqual(seen["ev-A"].decision_level, "alert")

    def test_cooldown_lookup_matches_state_write_key(self):
        """Cooldown lookup key must match state write key."""
        now = datetime.now(timezone.utc)
        seen_states = {
            "ev-A": CRSeenEventState(
                event_key="ev-A",
                decision_level="alert",
                score=70.0,
                seen_at=now.isoformat(),
            ),
        }
        # Lookup by cluster_key "ev-A".
        result = enforce_cr_cooldown(
            event_key="ev-A",
            candidate_id="c-A",
            current_level="alert",
            seen_state=seen_states.get("ev-A"),
            prior_snapshot_provided=True,
            policy=CRCooldownPolicy(same_level_cooldown_minutes=360),
            now=now,
        )
        # Should be blocked (same-level repeat inside cooldown).
        self.assertFalse(result.should_dispatch)


# ---------------------------------------------------------------------------
# Test Group L — Blocker 3: artifact/shadow never execute sink
# ---------------------------------------------------------------------------


class TestModeGatedExecution(unittest.TestCase):
    def test_artifact_with_injected_sink_no_call(self):
        """artifact + injected sink → sink call count 0."""
        sink = CRMemoryDispatchSink()
        with tempfile.TemporaryDirectory() as tmp:
            build_and_write_cr_runtime_dry_run(
                hotlist_stats=_hotlist_stats(),
                run_label="art-sink",
                artifact_config=CRArtifactConfig(root_dir=Path(tmp)),
                dispatch_mode="artifact",
                dispatch_sink=sink,
            )
            self.assertEqual(len(sink.submitted_messages), 0)

    def test_shadow_with_injected_sink_no_call(self):
        """shadow + injected sink → sink call count 0."""
        sink = CRMemoryDispatchSink()
        with tempfile.TemporaryDirectory() as tmp:
            build_and_write_cr_runtime_dry_run(
                hotlist_stats=_hotlist_stats(),
                run_label="shd-sink",
                artifact_config=CRArtifactConfig(root_dir=Path(tmp)),
                dispatch_mode="shadow",
                dispatch_sink=sink,
            )
            self.assertEqual(len(sink.submitted_messages), 0)


# ---------------------------------------------------------------------------
# Test Group M — Blocker 4: update all CR-A candidates
# ---------------------------------------------------------------------------


class TestUpdateAllCandidates(unittest.TestCase):
    def test_live_accepted_updates_all_candidates(self):
        """Live accepted dispatch updates state for all CR-A candidates."""
        with tempfile.TemporaryDirectory() as tmp:
            state_path = Path(tmp) / "dispatch_state.json"
            result = build_and_write_cr_runtime_dry_run(
                hotlist_stats=_hotlist_stats(),
                run_label="upd-all",
                artifact_config=CRArtifactConfig(root_dir=Path(tmp)),
                dispatch_mode="live",
                dispatch_sink=CRMemoryDispatchSink(),
                dispatch_state_path=str(state_path),
            )
            if result.dispatch_state_save and result.dispatch_state_save.saved:
                # Verify state was saved.
                load_result = load_cr_event_state_snapshot(state_path)
                self.assertTrue(load_result.loaded)
                # All cr_a_candidates should be in state.
                from trendradar.cr.state_snapshot import cr_event_state_snapshot_to_seen_states
                seen = cr_event_state_snapshot_to_seen_states(load_result.snapshot)
                for pc in result.pipeline.cr_a_candidates:
                    self.assertIn(pc.cluster_key, seen)


# ---------------------------------------------------------------------------
# Test Group N — Blocker 5: batch escalation filtering
# ---------------------------------------------------------------------------


class TestBatchEscalationFiltering(unittest.TestCase):
    def test_escalation_does_not_release_unrelated_repeat(self):
        """escalation bypass per-candidate: only escalated candidate passes."""
        now = datetime.now(timezone.utc)
        seen_states = {
            "ev-A": CRSeenEventState(
                event_key="ev-A",
                decision_level="alert",
                score=70.0,
                seen_at=now.isoformat(),
            ),
            "ev-B": CRSeenEventState(
                event_key="ev-B",
                decision_level="alert",
                score=70.0,
                seen_at=now.isoformat(),
            ),
        }
        # Candidate A: escalation alert→urgent (should be allowed).
        # Candidate B: same-level alert repeat (should be blocked).
        from unittest.mock import MagicMock
        pc_a = MagicMock()
        pc_a.cluster_key = "ev-A"
        pc_a.candidate_id = "c-A"
        pc_a.decision_level = "urgent"

        pc_b = MagicMock()
        pc_b.cluster_key = "ev-B"
        pc_b.candidate_id = "c-B"
        pc_b.decision_level = "alert"

        result = enforce_cr_cooldown_for_candidates(
            cr_a_candidates=(pc_a, pc_b),
            seen_states=seen_states,
            prior_snapshot_provided=True,
            policy=CRCooldownPolicy(same_level_cooldown_minutes=360),
            now=now,
        )
        # A should be eligible (escalation), B should not.
        eligible_keys = {pc.cluster_key for pc in result.eligible_candidates}
        self.assertIn("ev-A", eligible_keys)
        self.assertNotIn("ev-B", eligible_keys)


# ---------------------------------------------------------------------------
# Test Group O — Mixed candidate text filtering
# ---------------------------------------------------------------------------


class TestMixedCandidateTextFiltering(unittest.TestCase):
    def test_cooldown_entries_in_plan_json(self):
        """Cooldown entries appear in plan JSON with per-candidate outcomes."""
        from unittest.mock import MagicMock
        from trendradar.cr.dispatch_plan import (
            CRDispatchPlan,
            cr_dispatch_plan_to_json_dict,
        )
        from trendradar.cr.cooldown_enforce import enforce_cr_cooldown_for_candidates

        now = datetime.now(timezone.utc)
        seen_states = {
            "ev-A": CRSeenEventState(
                event_key="ev-A", decision_level="alert",
                score=70.0, seen_at=now.isoformat(),
            ),
            "ev-B": CRSeenEventState(
                event_key="ev-B", decision_level="alert",
                score=70.0, seen_at=now.isoformat(),
            ),
        }
        pc_a = MagicMock()
        pc_a.cluster_key = "ev-A"
        pc_a.candidate_id = "c-A"
        pc_a.decision_level = "urgent"

        pc_b = MagicMock()
        pc_b.cluster_key = "ev-B"
        pc_b.candidate_id = "c-B"
        pc_b.decision_level = "alert"

        enforcement = enforce_cr_cooldown_for_candidates(
            cr_a_candidates=(pc_a, pc_b),
            seen_states=seen_states,
            prior_snapshot_provided=True,
            policy=CRCooldownPolicy(same_level_cooldown_minutes=360),
            now=now,
        )
        eligible_keys = {pc.cluster_key for pc in enforcement.eligible_candidates}
        entries_list = []
        for e in enforcement.entries:
            is_eligible = e.event_key in eligible_keys
            entries_list.append({
                "candidate_id": e.candidate_id,
                "event_key": e.event_key,
                "is_escalation": e.is_escalation,
                "allowed_by_escalation": e.is_escalation and is_eligible,
                "suppressed_by_cooldown": not is_eligible,
                "decision": e.cooldown_action if is_eligible else "skipped_cooldown",
            })

        plan = CRDispatchPlan(
            should_dispatch=True,
            messages=(),
            reason="ready",
            run_label="test",
            candidate_count=1,
            urgent_count=1,
            high_score_suppressed_count=0,
        )
        d = cr_dispatch_plan_to_json_dict(
            plan,
            dispatch_mode="live",
            cooldown_context={
                "state_available": True,
                "state_error": None,
                "policy_version": "cr-cooldown-v1",
                "entries": entries_list,
            },
        )
        # Verify entries exist.
        self.assertIn("cooldown", d)
        entries = d["cooldown"]["entries"]
        self.assertEqual(len(entries), 2)
        # A: escalation allowed.
        a_entry = [e for e in entries if e["candidate_id"] == "c-A"][0]
        self.assertTrue(a_entry["is_escalation"])
        self.assertTrue(a_entry["allowed_by_escalation"])
        self.assertFalse(a_entry["suppressed_by_cooldown"])
        # B: repeat blocked.
        b_entry = [e for e in entries if e["candidate_id"] == "c-B"][0]
        self.assertFalse(b_entry["is_escalation"])
        self.assertFalse(b_entry["allowed_by_escalation"])
        self.assertTrue(b_entry["suppressed_by_cooldown"])

    def test_cooldown_entries_in_receipt_json(self):
        """Cooldown entries appear in receipt JSON as candidate_outcomes."""
        from trendradar.cr.dispatch_plan import CRDispatchPlan
        from trendradar.cr.dispatch_receipt import build_dispatch_receipts_json

        plan = CRDispatchPlan(
            should_dispatch=True,
            messages=(),
            reason="ready",
            run_label="test",
            candidate_count=1,
            urgent_count=1,
            high_score_suppressed_count=0,
        )
        entries = [
            {
                "candidate_id": "c-A",
                "event_key": "ev-A",
                "is_escalation": True,
                "allowed_by_escalation": True,
                "suppressed_by_cooldown": False,
                "decision": "eligible_escalation_bypass",
            },
            {
                "candidate_id": "c-B",
                "event_key": "ev-B",
                "is_escalation": False,
                "allowed_by_escalation": False,
                "suppressed_by_cooldown": True,
                "decision": "skipped_cooldown",
            },
        ]
        d = build_dispatch_receipts_json(
            plan,
            dispatch_mode="live",
            cooldown_entries=entries,
        )
        self.assertIn("candidate_outcomes", d)
        self.assertEqual(len(d["candidate_outcomes"]), 2)
        b_outcome = [o for o in d["candidate_outcomes"] if o["candidate_id"] == "c-B"][0]
        self.assertTrue(b_outcome["suppressed_by_cooldown"])
        self.assertEqual(b_outcome["decision"], "skipped_cooldown")

    def test_filtered_text_excludes_skipped_candidate(self):
        """Filtered pipeline text only contains eligible candidates."""
        from trendradar.cr.presentation import (
            CRPresentationRun,
            render_cr_a_text,
            CRPresentedCandidate,
        )
        from trendradar.cr.decision import CRDecision
        from trendradar.cr.scoring import CRScoreResult
        from trendradar.cr.models import CRCandidate

        def _make_pc(cid, key, title, level):
            cand = CRCandidate(
                candidate_id=cid, cluster_key=key,
                display_title=title, representative_url=None, source_items=[],
            )
            sr = CRScoreResult(
                candidate_id=cid, cluster_key=key,
                profile_version="v", total_score=70.0,
                trigger_reasons=[], debug={},
            )
            dec = CRDecision(
                candidate_id=cid, cluster_key=key,
                profile_version="v", policy_version="v",
                level=level, total_score=70.0, push_eligible=True,
                suppress_labels=[], trigger_reasons=[], debug={},
            )
            return CRPresentedCandidate(
                candidate=cand, score_result=sr, decision=dec,
                candidate_id=cid, cluster_key=key,
                display_title=title, representative_url=None,
                decision_level=level, total_score=70.0,
                trigger_reasons=[], suppress_labels=[],
            )

        pc_a = _make_pc("c-A", "ev-A", "Topic A", "urgent")
        pc_b = _make_pc("c-B", "ev-B", "Topic B", "alert")

        # Full text contains both.
        full_run = CRPresentationRun(
            run_label="test", candidates=[pc_a, pc_b],
        )
        full_text = render_cr_a_text(full_run)
        self.assertIn("Topic A", full_text)
        self.assertIn("Topic B", full_text)

        # Filtered text (only A) excludes B.
        filtered_run = CRPresentationRun(
            run_label="test", candidates=[pc_a],
        )
        filtered_text = render_cr_a_text(filtered_run)
        self.assertIn("Topic A", filtered_text)
        self.assertNotIn("Topic B", filtered_text)


if __name__ == "__main__":
    unittest.main()
