# coding=utf-8
"""
Tests for the pure CR-A event state snapshot boundary (PR10c).
"""

import inspect
import unittest

from trendradar.cr.decision import CRDecision
from trendradar.cr.models import CRCandidate
from trendradar.cr.presentation import CRPresentedCandidate
from trendradar.cr.scoring import CRScoreResult
from trendradar.cr.state_snapshot import (
    CR_EVENT_STATE_SCHEMA_VERSION,
    CREventStateEntry,
    CREventStateSnapshot,
    build_cr_event_state_entries_from_presented_candidates,
    build_cr_event_state_entry_from_presented_candidate,
    cr_event_state_snapshot_from_json_dict,
    cr_event_state_snapshot_to_json_dict,
    cr_event_state_snapshot_to_seen_states,
    empty_cr_event_state_snapshot,
    merge_cr_event_state_entries,
)
import trendradar.cr.state_snapshot as state_snapshot_module


class TestEmptySnapshot(unittest.TestCase):
    def test_empty_snapshot_has_schema_and_no_entries(self):
        snapshot = empty_cr_event_state_snapshot()
        self.assertEqual(snapshot.schema_version, CR_EVENT_STATE_SCHEMA_VERSION)
        self.assertEqual(snapshot.entries, ())

    def test_empty_snapshot_to_seen_states_is_empty(self):
        self.assertEqual(
            cr_event_state_snapshot_to_seen_states(
                empty_cr_event_state_snapshot()
            ),
            {},
        )


class TestJsonRoundTrip(unittest.TestCase):
    def test_round_trip_preserves_entry_fields(self):
        snapshot = CREventStateSnapshot(
            schema_version=CR_EVENT_STATE_SCHEMA_VERSION,
            entries=(
                CREventStateEntry(
                    event_key="cr-event-v1:abc",
                    decision_level="urgent",
                    score=92.5,
                    seen_at="2026-06-12T08:00:00+08:00",
                    title="广西兴安发生爆炸",
                    candidate_id="candidate-1",
                    event_key_version="cr-event-v1",
                ),
            ),
        )

        data = cr_event_state_snapshot_to_json_dict(snapshot)
        restored = cr_event_state_snapshot_from_json_dict(data)

        self.assertEqual(restored, snapshot)
        self.assertEqual(data["entries"][0]["title"], "广西兴安发生爆炸")
        self.assertEqual(data["entries"][0]["score"], 92.5)
        self.assertEqual(
            data["entries"][0]["seen_at"],
            "2026-06-12T08:00:00+08:00",
        )
        self.assertEqual(data["entries"][0]["candidate_id"], "candidate-1")
        self.assertEqual(data["entries"][0]["event_key_version"], "cr-event-v1")


class TestDuplicateMergeSemantics(unittest.TestCase):
    def test_updates_replace_previous_and_order_is_deterministic(self):
        previous = CREventStateSnapshot(
            schema_version=CR_EVENT_STATE_SCHEMA_VERSION,
            entries=(
                CREventStateEntry(event_key="event-b", decision_level="watch"),
                CREventStateEntry(event_key="event-a", decision_level="alert"),
            ),
        )
        before = previous

        merged = merge_cr_event_state_entries(
            previous,
            (
                CREventStateEntry(
                    event_key="event-b",
                    decision_level="urgent",
                    score=88.0,
                ),
                CREventStateEntry(event_key="event-c", decision_level="watch"),
            ),
        )

        self.assertEqual(previous, before)
        self.assertEqual(
            [entry.event_key for entry in merged.entries],
            ["event-a", "event-b", "event-c"],
        )
        by_key = {entry.event_key: entry for entry in merged.entries}
        self.assertEqual(by_key["event-b"].decision_level, "urgent")
        self.assertEqual(by_key["event-b"].score, 88.0)
        self.assertEqual(by_key["event-a"].decision_level, "alert")


class TestSeenStateConversion(unittest.TestCase):
    def test_converts_to_repeat_preview_seen_states(self):
        snapshot = CREventStateSnapshot(
            schema_version=CR_EVENT_STATE_SCHEMA_VERSION,
            entries=(
                CREventStateEntry(
                    event_key="event-1",
                    decision_level="alert",
                    score=70.0,
                    seen_at="2026-06-12T08:00:00+08:00",
                    title="Topic",
                    candidate_id="candidate-1",
                ),
            ),
        )

        states = cr_event_state_snapshot_to_seen_states(snapshot)
        state = states["event-1"]

        self.assertEqual(state.event_key, "event-1")
        self.assertEqual(state.decision_level, "alert")
        self.assertEqual(state.score, 70.0)
        self.assertEqual(state.seen_at, "2026-06-12T08:00:00+08:00")
        self.assertEqual(state.title, "Topic")
        self.assertEqual(state.candidate_id, "candidate-1")

    def test_rejects_schema_version_mismatch(self):
        snapshot = CREventStateSnapshot(
            schema_version="wrong",
            entries=(CREventStateEntry(event_key="event-1"),),
        )

        with self.assertRaisesRegex(
            ValueError,
            "event state snapshot schema_version mismatch",
        ):
            cr_event_state_snapshot_to_seen_states(snapshot)


class TestInvalidInput(unittest.TestCase):
    def test_missing_schema_version_is_rejected(self):
        with self.assertRaises(ValueError):
            cr_event_state_snapshot_from_json_dict({"entries": []})

    def test_blank_event_key_is_rejected(self):
        with self.assertRaises(ValueError):
            cr_event_state_snapshot_from_json_dict(
                {
                    "schema_version": CR_EVENT_STATE_SCHEMA_VERSION,
                    "entries": [{"event_key": " "}],
                }
            )

    def test_non_list_entries_is_rejected(self):
        with self.assertRaises(ValueError):
            cr_event_state_snapshot_from_json_dict(
                {
                    "schema_version": CR_EVENT_STATE_SCHEMA_VERSION,
                    "entries": {"event_key": "event-1"},
                }
            )

    def test_unknown_extra_fields_are_ignored(self):
        snapshot = cr_event_state_snapshot_from_json_dict(
            {
                "schema_version": CR_EVENT_STATE_SCHEMA_VERSION,
                "entries": [
                    {
                        "event_key": "event-1",
                        "decision_level": "alert",
                        "extra": "ignored",
                    }
                ],
                "extra_root": "ignored",
            }
        )

        self.assertEqual(len(snapshot.entries), 1)
        self.assertEqual(snapshot.entries[0].event_key, "event-1")
        self.assertEqual(snapshot.entries[0].decision_level, "alert")


class TestPresentedCandidateBuilder(unittest.TestCase):
    def _presented_candidate(self):
        candidate = CRCandidate(
            candidate_id="candidate-1",
            cluster_key="cluster-1",
            display_title="Topic",
            source_names=["weibo"],
        )
        score = CRScoreResult(
            candidate_id="candidate-1",
            cluster_key="cluster-1",
            profile_version="test-score",
            total_score=81.0,
        )
        decision = CRDecision(
            candidate_id="candidate-1",
            cluster_key="cluster-1",
            profile_version="test-score",
            policy_version="test-policy",
            level="urgent",
            total_score=81.0,
            push_eligible=True,
        )
        return CRPresentedCandidate(
            candidate=candidate,
            score_result=score,
            decision=decision,
            candidate_id="candidate-1",
            cluster_key="cluster-1",
            display_title="Topic",
            representative_url=None,
            decision_level="urgent",
            total_score=81.0,
        )

    def test_builds_entry_from_presented_candidate(self):
        pc = self._presented_candidate()
        entry = build_cr_event_state_entry_from_presented_candidate(
            pc,
            seen_at="2026-06-12T08:00:00+08:00",
        )

        self.assertTrue(entry.event_key.startswith("cr-event-v1:"))
        self.assertEqual(entry.decision_level, "urgent")
        self.assertEqual(entry.score, 81.0)
        self.assertEqual(entry.seen_at, "2026-06-12T08:00:00+08:00")
        self.assertEqual(entry.title, "Topic")
        self.assertEqual(entry.candidate_id, "candidate-1")
        self.assertEqual(entry.event_key_version, "cr-event-v1")

    def test_builds_entries_from_presented_candidates(self):
        entries = build_cr_event_state_entries_from_presented_candidates(
            (self._presented_candidate(),),
            seen_at="2026-06-12T08:00:00+08:00",
        )

        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0].candidate_id, "candidate-1")


class TestPurityGuard(unittest.TestCase):
    def test_module_source_has_no_forbidden_io_network_env_or_runtime(self):
        source = inspect.getsource(state_snapshot_module)
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
            "dispatch_plan",
            "runtime_dry_run",
            "state_store",
        )
        for fragment in forbidden_fragments:
            self.assertNotIn(fragment, source)


if __name__ == "__main__":
    unittest.main()
