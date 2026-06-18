# coding=utf-8
"""PR-CR-A7 deferred dispatch queue tests."""

import json
import tempfile
import unittest
from datetime import datetime
from pathlib import Path

from trendradar.cr.artifacts import CRArtifactConfig
from trendradar.cr.deferred_queue import (
    CRDeferredDispatchEntry,
    empty_deferred_dispatch_queue,
    load_deferred_dispatch_queue,
    ordered_entries_for_flush,
    save_deferred_dispatch_queue,
    stable_deferred_entry_id,
    upsert_deferred_entry,
)
from trendradar.cr.dispatch_executor import CRDispatchReceipt, CRMemoryDispatchSink
from trendradar.cr.runtime_dry_run import build_and_write_cr_runtime_dry_run
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


def _hotlist_stats(title: str = "Current A") -> list[dict]:
    def item(source_id: str) -> dict:
        return {
            "title": title,
            "source_name": source_id,
            "source_id": source_id,
            "ranks": [1],
            "count": 20,
            "first_time": "09:30",
            "last_time": "12:00",
            "url": f"https://example.com/{source_id}",
            "mobileUrl": "",
            "is_new": True,
            "rank_timeline": [
                {"time": "09:00", "rank": 5},
                {"time": "12:00", "rank": 1},
            ],
        }

    return [
        {
            "word": "AI",
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


class _RejectingSink:
    def submit(self, message, *, message_index):  # noqa: ANN001
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

    def test_ordering_urgent_before_alert_then_oldest(self):
        queue = empty_deferred_dispatch_queue()
        for entry in (
            _entry("alert-new", level="alert", deferred_at="2026-06-18T00:10:00+08:00"),
            _entry("urgent-new", level="urgent", deferred_at="2026-06-18T00:20:00+08:00"),
            _entry("urgent-old", level="urgent", deferred_at="2026-06-17T23:30:00+08:00"),
        ):
            queue = upsert_deferred_entry(queue, entry)
        ordered = ordered_entries_for_flush(queue)
        self.assertEqual(
            [entry.event_key for entry in ordered],
            ["urgent-old", "urgent-new", "alert-new"],
        )

    def test_dedupe_preserves_deferred_at_and_refreshes_same_level(self):
        queue = upsert_deferred_entry(
            empty_deferred_dispatch_queue(),
            _entry("ev-A", level="alert", title="Old", score=70.0, text="old text"),
        )
        queue = upsert_deferred_entry(
            queue,
            _entry(
                "ev-A",
                level="alert",
                deferred_at="2026-06-18T00:30:00+08:00",
                title="New",
                score=75.0,
                text="new text",
            ),
        )
        self.assertEqual(len(queue.entries), 1)
        entry = queue.entries[0]
        self.assertEqual(entry.deferred_at, "2026-06-17T23:30:00+08:00")
        self.assertEqual(entry.title, "New")
        self.assertEqual(entry.score, 75.0)
        self.assertEqual(entry.message_text, "new text")

    def test_urgent_supersedes_alert_without_duplicate(self):
        queue = upsert_deferred_entry(
            empty_deferred_dispatch_queue(),
            _entry("ev-A", level="alert"),
        )
        queue = upsert_deferred_entry(
            queue,
            _entry("ev-A", level="urgent", text="urgent text"),
        )
        self.assertEqual(len(queue.entries), 1)
        self.assertEqual(queue.entries[0].level, "urgent")
        self.assertEqual(queue.entries[0].message_text, "urgent text")


class TestDeferredQueueRuntime(unittest.TestCase):
    def _seed_queue(self, path: Path, *entries: CRDeferredDispatchEntry) -> None:
        queue = empty_deferred_dispatch_queue()
        for entry in entries:
            queue = upsert_deferred_entry(queue, entry)
        save = save_deferred_dispatch_queue(queue, path)
        self.assertTrue(save.saved, save.error)

    def test_flush_accepts_in_order_then_current_receipt(self):
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
                run_label="flush-current",
                artifact_config=CRArtifactConfig(root_dir=Path(tmp) / "art"),
                dispatch_mode="live",
                dispatch_sink=sink,
                dispatch_state_path=state_path,
                deferred_queue_path=queue_path,
                quiet_hours_env=_quiet_env(),
                now=_dt("2026-06-18T08:01:00+08:00"),
                urgent_threshold=999.0,
            )

            self.assertEqual(
                [message.text for message in sink.submitted_messages[:2]],
                ["urgent message", "alert message"],
            )
            receipts = json.loads(
                result.dispatch_receipt_json_paths.dispatch_receipt_latest_path.read_text(
                    encoding="utf-8"
                )
            )["receipts"]
            self.assertEqual(receipts[0]["detail"], "flushed_deferred")
            self.assertEqual(receipts[1]["detail"], "flushed_deferred")
            self.assertEqual(receipts[2]["status"], "accepted")
            queue = json.loads(queue_path.read_text(encoding="utf-8"))
            self.assertEqual(queue["entries"], [])
            state = load_cr_event_state_snapshot(state_path)
            self.assertTrue(state.loaded)
            self.assertGreaterEqual(len(state.snapshot.entries), 3)

    def test_flush_not_configured_and_failed_retain_queue(self):
        for sink in (None, _RejectingSink(), _RaisingSink()):
            with self.subTest(sink=type(sink).__name__ if sink else "None"):
                with tempfile.TemporaryDirectory() as tmp:
                    queue_path = Path(tmp) / "queue.json"
                    self._seed_queue(queue_path, _entry("alert-A"))
                    result = build_and_write_cr_runtime_dry_run(
                        hotlist_stats=[],
                        run_label="flush-retain",
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
