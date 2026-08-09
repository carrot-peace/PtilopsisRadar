# coding=utf-8
"""PR-CR-A7 deferred dispatch queue tests."""

import json
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from trendradar.cr.artifacts import CRArtifactConfig
from trendradar.cr.decision import CRDecisionPolicy
from trendradar.cr.deferred_queue import (
    CRDeferredDispatchEntry,
    CRDeferredQueueSaveResult,
    empty_deferred_dispatch_queue,
    expire_deferred_entries,
    load_deferred_dispatch_queue,
    ordered_entries_for_flush,
    save_deferred_dispatch_queue,
    stable_deferred_entry_id,
    upsert_deferred_entry,
)
from trendradar.cr.dispatch_executor import CRDispatchReceipt, CRMemoryDispatchSink
from trendradar.cr.event_identity import stable_event_key_for_candidate
from trendradar.cr.models import CRCandidate
from trendradar.cr.pipeline import CRPipelineConfig
from trendradar.cr.runtime_dry_run import (
    _deferred_receipts_for_upserts,
    _queue_with_candidates,
    build_and_write_cr_runtime_dry_run,
)
from trendradar.cr.state_store import load_cr_event_state_snapshot


def _dt(value: str) -> datetime:
    return datetime.fromisoformat(value)


def _quiet_env() -> dict[str, str]:
    return {
        "PTILOPSIS_CR_QUIET_HOURS_ENABLED": "1",
        "PTILOPSIS_CR_TIMEZONE": "Asia/Shanghai",
        "PTILOPSIS_CR_QUIET_HOURS_START": "23:00",
        "PTILOPSIS_CR_QUIET_HOURS_END": "08:00",
    }


def _hotlist_stats(
    title: str = "Current A", *, word: str = "AI", event_id: str | None = None
) -> list[dict]:
    def item(source_id: str) -> dict:
        return {
            "title": title,
            "source_name": source_id,
            "source_id": source_id,
            "ranks": [1],
            "count": 20,
            "first_time": "09:30",
            "last_time": "12:00",
            "url": (
                f"https://example.com/{source_id}"
                + (f"/{event_id}" if event_id else "")
            ),
            "mobileUrl": "",
            "is_new": True,
            "rank_timeline": [
                {"time": "09:00", "rank": 5},
                {"time": "12:00", "rank": 1},
            ],
        }

    return [
        {
            "word": word,
            "titles": [item("weibo"), item("zhihu"), item("baidu")],
            "count": 3,
            "position": 0,
        }
    ]


def _entry(
    event_key: str,
    *,
    level: str = "alert",
    deferred_at: str = "2026-06-17T23:30:00+08:00",
    title: str | None = None,
    score: float = 70.0,
    text: str | None = None,
) -> CRDeferredDispatchEntry:
    return CRDeferredDispatchEntry(
        entry_id=stable_deferred_entry_id(event_key),
        event_key=event_key,
        candidate_id=f"c-{event_key}",
        title=title or f"Title {event_key}",
        level=level,
        score=score,
        deferred_at=deferred_at,
        deferred_until="2026-06-18T08:00:00+08:00",
        reason="quiet_hours",
        message_text=text or f"Message {event_key}",
        candidate_payload={"event_key": event_key, "level": level},
        last_seen_at=deferred_at,
    )


def _presented_candidate(title: str, *, level: str = "alert") -> object:
    raw = CRCandidate(
        candidate_id=f"candidate-{title}",
        cluster_key=f"cluster-{title}",
        display_title=title,
    )
    return SimpleNamespace(
        candidate=raw,
        candidate_id=raw.candidate_id,
        display_title=title,
        decision_level=level,
        total_score=75.0,
        representative_url=None,
        trigger_reasons=["test"],
        suppress_labels=[],
    )


class _RejectingSink:
    def __init__(self):
        self.submit_calls = []

    def submit(self, message, *, message_index):  # noqa: ANN001
        self.submit_calls.append((message, message_index))
        return CRDispatchReceipt(
            message_index=message_index,
            accepted=False,
            status="rejected",
            detail="test_rejected",
            candidate_count=message.candidate_count,
            run_label=message.run_label,
        )


class _RaisingSink:
    def submit(self, message, *, message_index):  # noqa: ANN001
        raise TimeoutError("timeout")


class TestDeferredQueueStore(unittest.TestCase):
    def test_missing_queue_is_empty_and_malformed_fails_closed(self):
        with tempfile.TemporaryDirectory() as tmp:
            missing = Path(tmp) / "missing.json"
            result = load_deferred_dispatch_queue(missing)
            self.assertIsNone(result.error)
            self.assertFalse(result.loaded)
            self.assertEqual(result.queue.entries, ())

            malformed = Path(tmp) / "queue.json"
            malformed.write_text("{not-json", encoding="utf-8")
            result = load_deferred_dispatch_queue(malformed)
            self.assertIsNotNone(result.error)
            self.assertEqual(malformed.read_text(encoding="utf-8"), "{not-json")

    def test_invalid_deferred_at_fails_closed_without_rewriting_queue(self):
        with tempfile.TemporaryDirectory() as tmp:
            queue_path = Path(tmp) / "queue.json"
            saved = save_deferred_dispatch_queue(
                upsert_deferred_entry(
                    empty_deferred_dispatch_queue(), _entry("invalid-time")
                ).queue,
                queue_path,
            )
            self.assertTrue(saved.saved, saved.error)
            raw = json.loads(queue_path.read_text(encoding="utf-8"))
            raw["entries"][0]["deferred_at"] = "not-an-iso-timestamp"
            queue_path.write_text(json.dumps(raw), encoding="utf-8")

            result = load_deferred_dispatch_queue(queue_path)

            self.assertFalse(result.loaded)
            self.assertEqual(result.queue.entries, ())
            self.assertIsNotNone(result.error)
            self.assertIn("deferred_at", result.error)
            self.assertEqual(
                json.loads(queue_path.read_text(encoding="utf-8")), raw
            )

    def test_ordering_urgent_before_alert_then_oldest(self):
        queue = empty_deferred_dispatch_queue()
        for entry in (
            _entry("alert-new", level="alert", deferred_at="2026-06-18T00:10:00+08:00"),
            _entry("urgent-new", level="urgent", deferred_at="2026-06-18T00:20:00+08:00"),
            _entry("urgent-old", level="urgent", deferred_at="2026-06-17T23:30:00+08:00"),
        ):
            queue = upsert_deferred_entry(queue, entry).queue
        ordered = ordered_entries_for_flush(queue)
        self.assertEqual(
            [entry.event_key for entry in ordered],
            ["urgent-old", "urgent-new", "alert-new"],
        )

    def test_dedupe_preserves_deferred_at_and_refreshes_same_level(self):
        first = upsert_deferred_entry(
            empty_deferred_dispatch_queue(),
            _entry("ev-A", level="alert", title="Old", score=70.0, text="old text"),
        )
        self.assertEqual(first.outcome, "inserted")
        refreshed = upsert_deferred_entry(
            first.queue,
            _entry(
                "ev-A",
                level="alert",
                deferred_at="2026-06-18T00:30:00+08:00",
                title="New",
                score=75.0,
                text="new text",
            ),
        )
        self.assertEqual(refreshed.outcome, "refreshed")
        self.assertEqual(refreshed.reason, "same_level_refresh")
        queue = refreshed.queue
        self.assertEqual(len(queue.entries), 1)
        entry = queue.entries[0]
        self.assertEqual(entry.deferred_at, "2026-06-17T23:30:00+08:00")
        self.assertEqual(entry.title, "New")
        self.assertEqual(entry.score, 75.0)
        self.assertEqual(entry.message_text, "new text")

    def test_expiry_uses_first_deferred_at_and_does_not_extend_on_refresh(self):
        queue = empty_deferred_dispatch_queue()
        queue = upsert_deferred_entry(
            queue,
            _entry(
                "expired",
                deferred_at="2026-06-17T19:59:59+08:00",
            ),
        ).queue
        queue = upsert_deferred_entry(
            queue,
            _entry(
                "recent",
                deferred_at="2026-06-18T00:00:01+08:00",
            ),
        ).queue

        pruned, expired = expire_deferred_entries(
            queue,
            now=_dt("2026-06-18T08:00:00+08:00"),
        )

        self.assertEqual([entry.event_key for entry in expired], ["expired"])
        self.assertEqual(
            [entry.event_key for entry in pruned.entries], ["recent"]
        )

        refreshed = upsert_deferred_entry(
            queue,
            _entry(
                "expired",
                deferred_at="2026-06-18T07:59:59+08:00",
            ),
        ).queue
        refreshed_pruned, refreshed_expired = expire_deferred_entries(
            refreshed,
            now=_dt("2026-06-18T08:00:00+08:00"),
        )
        self.assertEqual(
            [entry.event_key for entry in refreshed_expired], ["expired"]
        )
        self.assertEqual(
            [entry.event_key for entry in refreshed_pruned.entries], ["recent"]
        )

    def test_urgent_supersedes_alert_without_duplicate(self):
        queue = upsert_deferred_entry(
            empty_deferred_dispatch_queue(),
            _entry("ev-A", level="alert"),
        ).queue
        result = upsert_deferred_entry(
            queue,
            _entry("ev-A", level="urgent", text="urgent text"),
        )
        self.assertEqual(result.outcome, "refreshed")
        self.assertEqual(result.reason, "higher_level_refresh")
        self.assertEqual(result.event_key, "ev-A")
        self.assertEqual(result.candidate_id, "c-ev-A")
        queue = result.queue
        self.assertEqual(len(queue.entries), 1)
        self.assertEqual(queue.entries[0].level, "urgent")
        self.assertEqual(queue.entries[0].message_text, "urgent text")

    def test_lower_level_is_skipped_with_explicit_reason(self):
        queue = upsert_deferred_entry(
            empty_deferred_dispatch_queue(),
            _entry("ev-A", level="urgent", text="urgent text"),
        ).queue

        result = upsert_deferred_entry(
            queue,
            _entry("ev-A", level="alert", text="alert text"),
        )

        self.assertEqual(result.outcome, "skipped")
        self.assertEqual(result.reason, "existing_higher_level")
        self.assertEqual(result.queue, queue)

    def test_batch_upsert_reports_partial_success_without_false_receipt(self):
        lower = _presented_candidate("Existing Event", level="alert")
        inserted = _presented_candidate("New Event", level="alert")
        lower_key = stable_event_key_for_candidate(lower)
        queue = upsert_deferred_entry(
            empty_deferred_dispatch_queue(),
            _entry(lower_key, level="urgent"),
        ).queue

        updated, outcomes = _queue_with_candidates(
            queue,
            (lower, inserted),
            deferred_at="2026-06-17T23:30:00+08:00",
            deferred_until="2026-06-18T08:00:00+08:00",
            run_label="partial-upsert",
            high_score_suppressed_count=0,
        )
        receipts = _deferred_receipts_for_upserts(
            outcomes,
            deferred_until="2026-06-18T08:00:00+08:00",
            queue_state_current=True,
        )

        self.assertEqual([item.outcome for item in outcomes], ["skipped", "inserted"])
        self.assertEqual(
            [receipt["status"] for receipt in receipts],
            ["skipped_deferred_queue_upsert", "deferred_quiet_hours"],
        )
        self.assertEqual(
            [receipt["deferred_upsert_reason"] for receipt in receipts],
            ["existing_higher_level", "new_entry"],
        )
        self.assertEqual(len(updated.entries), 2)
        self.assertEqual(
            {entry.event_key for entry in updated.entries},
            {lower_key, stable_event_key_for_candidate(inserted)},
        )

    def test_deferred_message_preserves_coverage_warning(self):
        candidate = _presented_candidate("Coverage Event", level="alert")
        updated, outcomes = _queue_with_candidates(
            empty_deferred_dispatch_queue(),
            (candidate,),
            deferred_at="2026-07-13T01:00:00+08:00",
            deferred_until="2026-07-13T08:00:00+08:00",
            run_label="coverage-warning",
            high_score_suppressed_count=0,
            coverage_warning="Collection coverage: 1/4 (3 failed)",
        )
        self.assertEqual(outcomes[0].outcome, "inserted")
        self.assertIn(
            "Collection coverage: 1/4 (3 failed)",
            updated.entries[0].message_text,
        )


class TestDeferredQueueRuntime(unittest.TestCase):
    def _seed_queue(self, path: Path, *entries: CRDeferredDispatchEntry) -> None:
        queue = empty_deferred_dispatch_queue()
        for entry in entries:
            queue = upsert_deferred_entry(queue, entry).queue
        save = save_deferred_dispatch_queue(queue, path)
        self.assertTrue(save.saved, save.error)

    def test_unmatched_queue_entries_are_not_sent_and_current_receipt_is_single(self):
        with tempfile.TemporaryDirectory() as tmp:
            queue_path = Path(tmp) / "queue.json"
            state_path = Path(tmp) / "state.json"
            self._seed_queue(
                queue_path,
                _entry("alert-A", level="alert", text="alert message"),
                _entry("urgent-B", level="urgent", text="urgent message"),
            )
            sink = CRMemoryDispatchSink()
            result = build_and_write_cr_runtime_dry_run(
                hotlist_stats=_hotlist_stats("Current Event"),
                run_label="reconcile-current",
                artifact_config=CRArtifactConfig(root_dir=Path(tmp) / "art"),
                dispatch_mode="live",
                dispatch_sink=sink,
                dispatch_state_path=state_path,
                deferred_queue_path=queue_path,
                quiet_hours_env=_quiet_env(),
                now=_dt("2026-06-18T08:01:00+08:00"),
                urgent_threshold=999.0,
            )

            self.assertEqual(len(sink.submitted_messages), 1)
            self.assertIn("Current Event", sink.submitted_messages[0].text)
            receipts = json.loads(
                result.dispatch_receipt_json_paths.dispatch_receipt_latest_path.read_text(
                    encoding="utf-8"
                )
            )["receipts"]
            self.assertEqual(receipts[-1]["status"], "accepted")
            queue = json.loads(queue_path.read_text(encoding="utf-8"))
            self.assertEqual(len(queue["entries"]), 2)
            state = load_cr_event_state_snapshot(state_path)
            self.assertTrue(state.loaded)
            self.assertEqual(len(state.snapshot.entries), 1)

    def test_same_event_reconcile_alert_and_current_urgent_persists_urgent(self):
        with tempfile.TemporaryDirectory() as tmp:
            queue_path = Path(tmp) / "queue.json"
            state_path = Path(tmp) / "state.json"
            artifact_root = Path(tmp) / "art"
            sink = CRMemoryDispatchSink()
            common = {
                "hotlist_stats": _hotlist_stats("Escalating Event"),
                "artifact_config": CRArtifactConfig(root_dir=artifact_root),
                "dispatch_mode": "live",
                "dispatch_sink": sink,
                "dispatch_state_path": state_path,
                "deferred_queue_path": queue_path,
                "quiet_hours_env": _quiet_env(),
            }

            build_and_write_cr_runtime_dry_run(
                **common,
                run_label="defer-alert",
                now=_dt("2026-06-17T23:30:00+08:00"),
                urgent_threshold=999.0,
            )
            queue_before_flush = load_deferred_dispatch_queue(queue_path).queue
            self.assertEqual(len(queue_before_flush.entries), 1)
            event_key = queue_before_flush.entries[0].event_key

            morning_result = build_and_write_cr_runtime_dry_run(
                **common,
                run_label="reconcile-and-escalate",
                now=_dt("2026-06-18T08:01:00+08:00"),
                pipeline_config=CRPipelineConfig(
                    decision=CRDecisionPolicy(urgent_threshold=1.0)
                ),
                urgent_threshold=1.0,
            )

            state = load_cr_event_state_snapshot(state_path)
            by_key = {entry.event_key: entry for entry in state.snapshot.entries}
            self.assertEqual(by_key[event_key].decision_level, "urgent")
            submitted_after_escalation = len(sink.submitted_messages)
            self.assertEqual(submitted_after_escalation, 1)
            queue = json.loads(queue_path.read_text(encoding="utf-8"))
            self.assertEqual(queue["entries"], [])
            plan = json.loads(
                morning_result.dispatch_plan_json_paths.dispatch_plan_latest_path.read_text(
                    encoding="utf-8"
                )
            )
            self.assertEqual(plan["quiet_hours"]["reconciled_count"], 1)

            build_and_write_cr_runtime_dry_run(
                **common,
                run_label="repeat-urgent",
                now=_dt("2026-06-18T08:02:00+08:00"),
                pipeline_config=CRPipelineConfig(
                    decision=CRDecisionPolicy(urgent_threshold=1.0)
                ),
                urgent_threshold=1.0,
            )

            self.assertEqual(
                len(sink.submitted_messages),
                submitted_after_escalation + 1,
            )
            repeat_summary = sink.submitted_messages[-1]
            self.assertEqual(repeat_summary.candidate_count, 0)
            self.assertIn(
                "Suppressed (high-score): 1", repeat_summary.text
            )

    def test_matching_current_rejection_keeps_deferred_entry(self):
        with tempfile.TemporaryDirectory() as tmp:
            queue_path = Path(tmp) / "queue.json"
            state_path = Path(tmp) / "state.json"
            common = {
                "hotlist_stats": _hotlist_stats("Rejected Current"),
                "artifact_config": CRArtifactConfig(root_dir=Path(tmp) / "art"),
                "dispatch_mode": "live",
                "dispatch_state_path": state_path,
                "deferred_queue_path": queue_path,
                "quiet_hours_env": _quiet_env(),
                "urgent_threshold": 999.0,
            }

            build_and_write_cr_runtime_dry_run(
                **common,
                run_label="defer-for-rejection",
                dispatch_sink=CRMemoryDispatchSink(),
                now=_dt("2026-06-17T23:30:00+08:00"),
            )
            self.assertEqual(
                len(load_deferred_dispatch_queue(queue_path).queue.entries), 1
            )

            sink = _RejectingSink()
            result = build_and_write_cr_runtime_dry_run(
                **common,
                run_label="reject-current",
                dispatch_sink=sink,
                now=_dt("2026-06-18T08:01:00+08:00"),
            )

            self.assertEqual(len(sink.submit_calls), 1)
            queue = load_deferred_dispatch_queue(queue_path).queue
            self.assertEqual(len(queue.entries), 1)
            self.assertIn("Rejected Current", sink.submit_calls[0][0].text)
            receipts = json.loads(
                result.dispatch_receipt_json_paths.dispatch_receipt_latest_path.read_text(
                    encoding="utf-8"
                )
            )["receipts"]
            self.assertFalse(receipts[-1]["accepted"])

    def test_multiple_overlaps_send_one_current_message(self):
        with tempfile.TemporaryDirectory() as tmp:
            queue_path = Path(tmp) / "queue.json"
            stats = (
                _hotlist_stats("Alpha Event", word="quake", event_id="a")
                + _hotlist_stats("Beta Story", word="election", event_id="b")
            )
            common = {
                "hotlist_stats": stats,
                "artifact_config": CRArtifactConfig(root_dir=Path(tmp) / "art"),
                "dispatch_mode": "live",
                "deferred_queue_path": queue_path,
                "quiet_hours_env": _quiet_env(),
                "urgent_threshold": 999.0,
            }

            build_and_write_cr_runtime_dry_run(
                **common,
                run_label="defer-multiple",
                dispatch_sink=CRMemoryDispatchSink(),
                now=_dt("2026-06-17T23:30:00+08:00"),
            )
            self.assertEqual(
                len(load_deferred_dispatch_queue(queue_path).queue.entries), 2
            )

            sink = CRMemoryDispatchSink()
            result = build_and_write_cr_runtime_dry_run(
                **common,
                run_label="reconcile-multiple",
                dispatch_sink=sink,
                now=_dt("2026-06-18T08:01:00+08:00"),
            )

            self.assertEqual(len(sink.submitted_messages), 1)
            self.assertIn("reconcile-multiple", sink.submitted_messages[0].text)
            self.assertIn("Alpha Event", sink.submitted_messages[0].text)
            self.assertIn("Beta Story", sink.submitted_messages[0].text)
            self.assertEqual(
                load_deferred_dispatch_queue(queue_path).queue.entries, ()
            )
            plan = json.loads(
                result.dispatch_plan_json_paths.dispatch_plan_latest_path.read_text(
                    encoding="utf-8"
                )
            )
            self.assertEqual(plan["quiet_hours"]["reconciled_count"], 2)

    def test_expired_queue_is_pruned_without_sending_history(self):
        with tempfile.TemporaryDirectory() as tmp:
            queue_path = Path(tmp) / "queue.json"
            self._seed_queue(
                queue_path,
                _entry(
                    "expired-history",
                    deferred_at="2026-06-17T19:59:59+08:00",
                    text="stale deferred history",
                ),
            )
            sink = CRMemoryDispatchSink()
            result = build_and_write_cr_runtime_dry_run(
                hotlist_stats=[],
                run_label="expire-history",
                artifact_config=CRArtifactConfig(root_dir=Path(tmp) / "art"),
                dispatch_mode="live",
                dispatch_sink=sink,
                deferred_queue_path=queue_path,
                quiet_hours_env=_quiet_env(),
                now=_dt("2026-06-18T08:01:00+08:00"),
            )

            self.assertEqual(sink.submitted_messages, [])
            self.assertEqual(
                load_deferred_dispatch_queue(queue_path).queue.entries, ()
            )
            plan = json.loads(
                result.dispatch_plan_json_paths.dispatch_plan_latest_path.read_text(
                    encoding="utf-8"
                )
            )
            self.assertEqual(plan["quiet_hours"]["expired_count"], 1)
            self.assertEqual(plan["quiet_hours"]["reconciled_count"], 0)

    def test_missing_or_failed_current_send_retain_queue(self):
        for sink in (None, _RejectingSink(), _RaisingSink()):
            with self.subTest(sink=type(sink).__name__ if sink else "None"):
                with tempfile.TemporaryDirectory() as tmp:
                    queue_path = Path(tmp) / "queue.json"
                    self._seed_queue(queue_path, _entry("alert-A"))
                    result = build_and_write_cr_runtime_dry_run(
                        hotlist_stats=[],
                        run_label="reconcile-retain",
                        artifact_config=CRArtifactConfig(root_dir=Path(tmp) / "art"),
                        dispatch_mode="live",
                        dispatch_sink=sink,
                        deferred_queue_path=queue_path,
                        quiet_hours_env=_quiet_env(),
                        now=_dt("2026-06-18T08:01:00+08:00"),
                    )
                    queue = json.loads(queue_path.read_text(encoding="utf-8"))
                    self.assertEqual(len(queue["entries"]), 1)
                    receipts = json.loads(
                        result.dispatch_receipt_json_paths.dispatch_receipt_latest_path.read_text(
                            encoding="utf-8"
                        )
                    )["receipts"]
                    self.assertFalse(receipts[0]["accepted"])

    def test_post_dispatch_queue_cleanup_failure_is_reported(self):
        with tempfile.TemporaryDirectory() as tmp:
            queue_path = Path(tmp) / "queue.json"
            state_path = Path(tmp) / "state.json"
            artifact_root = Path(tmp) / "art"
            sink = CRMemoryDispatchSink()
            common = {
                "hotlist_stats": _hotlist_stats(
                    "Cleanup Failure Event", event_id="cleanup"
                ),
                "artifact_config": CRArtifactConfig(root_dir=artifact_root),
                "dispatch_mode": "live",
                "dispatch_sink": sink,
                "dispatch_state_path": state_path,
                "deferred_queue_path": queue_path,
                "quiet_hours_env": _quiet_env(),
                "urgent_threshold": 999.0,
            }
            build_and_write_cr_runtime_dry_run(
                **common,
                run_label="cleanup-failure-defer",
                now=_dt("2026-06-17T23:30:00+08:00"),
            )

            failed_save = Mock(
                return_value=CRDeferredQueueSaveResult(
                    saved=False,
                    error="unable to save deferred queue: OSError",
                    path=str(queue_path),
                )
            )
            with patch.dict(
                build_and_write_cr_runtime_dry_run.__globals__,
                {"save_deferred_dispatch_queue": failed_save},
            ):
                result = build_and_write_cr_runtime_dry_run(
                    **common,
                    run_label="cleanup-failure-reconcile",
                    now=_dt("2026-06-18T08:01:00+08:00"),
                )

            plan = json.loads(
                result.dispatch_plan_json_paths.dispatch_plan_latest_path.read_text(
                    encoding="utf-8"
                )
            )
            self.assertEqual(
                plan["quiet_hours"]["decision"],
                "skipped_deferred_queue_error",
            )
            self.assertEqual(
                plan["quiet_hours"]["reason"],
                "deferred_queue_cleanup_failed",
            )
            receipt = json.loads(
                result.dispatch_receipt_json_paths.dispatch_receipt_latest_path.read_text(
                    encoding="utf-8"
                )
            )
            statuses = [item["status"] for item in receipt["receipts"]]
            self.assertIn("accepted", statuses)
            self.assertIn("skipped_deferred_queue_error", statuses)
            self.assertEqual(
                len(load_deferred_dispatch_queue(queue_path).queue.entries), 1
            )

    def test_malformed_queue_blocks_current_send_and_preserves_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            queue_path = Path(tmp) / "queue.json"
            queue_path.write_text("{bad-json", encoding="utf-8")
            sink = CRMemoryDispatchSink()
            result = build_and_write_cr_runtime_dry_run(
                hotlist_stats=_hotlist_stats("Current Blocked"),
                run_label="queue-error",
                artifact_config=CRArtifactConfig(root_dir=Path(tmp) / "art"),
                dispatch_mode="live",
                dispatch_sink=sink,
                deferred_queue_path=queue_path,
                quiet_hours_env=_quiet_env(),
                now=_dt("2026-06-18T08:01:00+08:00"),
                urgent_threshold=999.0,
            )
            self.assertEqual(sink.submitted_messages, [])
            self.assertEqual(queue_path.read_text(encoding="utf-8"), "{bad-json")
            receipts = json.loads(
                result.dispatch_receipt_json_paths.dispatch_receipt_latest_path.read_text(
                    encoding="utf-8"
                )
            )["receipts"]
            self.assertEqual(receipts[0]["status"], "skipped_deferred_queue_error")


if __name__ == "__main__":
    unittest.main()
