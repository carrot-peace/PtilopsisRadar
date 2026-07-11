# coding=utf-8
"""PR-CR-A7 quiet-hours policy tests."""

import json
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import Mock, patch

from trendradar.cr.artifacts import CRArtifactConfig
from trendradar.cr.decision import CRDecisionPolicy
from trendradar.cr.dispatch_executor import CRDispatchReceipt, CRMemoryDispatchSink
from trendradar.cr.deferred_queue import CRDeferredQueueSaveResult
from trendradar.cr.pipeline import CRPipelineConfig
from trendradar.cr.quiet_hours import evaluate_cr_quiet_hours
from trendradar.cr.runtime_dry_run import build_and_write_cr_runtime_dry_run
from trendradar.cr.state_store import load_cr_event_state_snapshot


def _dt(value: str) -> datetime:
    return datetime.fromisoformat(value)


def _env(**overrides: str) -> dict[str, str]:
    base = {
        "PTILOPSIS_CR_QUIET_HOURS_ENABLED": "1",
        "PTILOPSIS_CR_TIMEZONE": "Asia/Shanghai",
        "PTILOPSIS_CR_QUIET_HOURS_START": "23:00",
        "PTILOPSIS_CR_QUIET_HOURS_END": "08:00",
    }
    base.update(overrides)
    return base


def _hotlist_stats(title: str = "AI Title") -> list[dict]:
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


def _latest_receipts(result) -> dict:  # noqa: ANN001
    path = result.dispatch_receipt_json_paths.dispatch_receipt_latest_path
    return json.loads(path.read_text(encoding="utf-8"))


def _latest_plan(result) -> dict:  # noqa: ANN001
    path = result.dispatch_plan_json_paths.dispatch_plan_latest_path
    return json.loads(path.read_text(encoding="utf-8"))


def _urgent_pipeline_config() -> CRPipelineConfig:
    return CRPipelineConfig(decision=CRDecisionPolicy(urgent_threshold=1.0))


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


class TestQuietHoursTimeEvaluation(unittest.TestCase):
    def test_overnight_window(self):
        env = _env()
        self.assertTrue(
            evaluate_cr_quiet_hours(env, now=_dt("2026-06-17T23:30:00+08:00")).in_quiet_hours
        )
        self.assertTrue(
            evaluate_cr_quiet_hours(env, now=_dt("2026-06-18T07:59:00+08:00")).in_quiet_hours
        )
        self.assertFalse(
            evaluate_cr_quiet_hours(env, now=_dt("2026-06-18T08:00:00+08:00")).in_quiet_hours
        )
        self.assertFalse(
            evaluate_cr_quiet_hours(env, now=_dt("2026-06-17T22:59:00+08:00")).in_quiet_hours
        )

    def test_non_overnight_window(self):
        env = _env(
            PTILOPSIS_CR_QUIET_HOURS_START="12:00",
            PTILOPSIS_CR_QUIET_HOURS_END="14:00",
        )
        self.assertTrue(
            evaluate_cr_quiet_hours(env, now=_dt("2026-06-17T13:00:00+08:00")).in_quiet_hours
        )
        self.assertFalse(
            evaluate_cr_quiet_hours(env, now=_dt("2026-06-17T15:00:00+08:00")).in_quiet_hours
        )

    def test_invalid_config_and_equal_window(self):
        bad_tz = evaluate_cr_quiet_hours(
            _env(PTILOPSIS_CR_TIMEZONE="Bad/Zone"),
            now=_dt("2026-06-17T23:30:00+08:00"),
        )
        self.assertEqual(bad_tz.decision, "quiet_hours_config_error")
        bad_time = evaluate_cr_quiet_hours(
            _env(PTILOPSIS_CR_QUIET_HOURS_START="24:00"),
            now=_dt("2026-06-17T23:30:00+08:00"),
        )
        self.assertEqual(bad_time.decision, "quiet_hours_config_error")
        equal = evaluate_cr_quiet_hours(
            _env(
                PTILOPSIS_CR_QUIET_HOURS_START="08:00",
                PTILOPSIS_CR_QUIET_HOURS_END="08:00",
            ),
            now=_dt("2026-06-17T08:00:00+08:00"),
        )
        self.assertFalse(equal.in_quiet_hours)
        self.assertFalse(equal.window_enabled)


class TestQuietHoursRuntime(unittest.TestCase):
    def test_alert_deferred_during_quiet_hours(self):
        with tempfile.TemporaryDirectory() as tmp:
            queue_path = Path(tmp) / "queue.json"
            state_path = Path(tmp) / "state.json"
            sink = CRMemoryDispatchSink()
            result = build_and_write_cr_runtime_dry_run(
                hotlist_stats=_hotlist_stats("Alert A"),
                run_label="alert-defer",
                artifact_config=CRArtifactConfig(root_dir=Path(tmp) / "art"),
                dispatch_mode="live",
                dispatch_sink=sink,
                dispatch_state_path=state_path,
                deferred_queue_path=queue_path,
                quiet_hours_env=_env(),
                now=_dt("2026-06-17T23:30:00+08:00"),
                urgent_threshold=999.0,
            )

            self.assertEqual(sink.submitted_messages, [])
            receipts = _latest_receipts(result)["receipts"]
            self.assertEqual(receipts[0]["status"], "deferred_quiet_hours")
            self.assertFalse(receipts[0]["accepted"])
            queue = json.loads(queue_path.read_text(encoding="utf-8"))
            self.assertEqual(len(queue["entries"]), 1)
            self.assertFalse(state_path.exists())

    def test_urgent_deferred_when_bypass_disabled(self):
        with tempfile.TemporaryDirectory() as tmp:
            queue_path = Path(tmp) / "queue.json"
            sink = CRMemoryDispatchSink()
            result = build_and_write_cr_runtime_dry_run(
                hotlist_stats=_hotlist_stats("Urgent A"),
                run_label="urgent-defer",
                artifact_config=CRArtifactConfig(root_dir=Path(tmp) / "art"),
                dispatch_mode="live",
                dispatch_sink=sink,
                deferred_queue_path=queue_path,
                quiet_hours_env=_env(PTILOPSIS_CR_QUIET_HOURS_ALLOW_URGENT="0"),
                now=_dt("2026-06-17T23:30:00+08:00"),
                pipeline_config=_urgent_pipeline_config(),
            )

            self.assertEqual(sink.submitted_messages, [])
            self.assertEqual(_latest_receipts(result)["receipts"][0]["status"], "deferred_quiet_hours")
            queue = json.loads(queue_path.read_text(encoding="utf-8"))
            self.assertEqual(queue["entries"][0]["level"], "urgent")

    def test_urgent_bypass_accepted_updates_state_and_not_queue(self):
        with tempfile.TemporaryDirectory() as tmp:
            queue_path = Path(tmp) / "queue.json"
            state_path = Path(tmp) / "state.json"
            sink = CRMemoryDispatchSink()
            result = build_and_write_cr_runtime_dry_run(
                hotlist_stats=_hotlist_stats("Urgent Bypass"),
                run_label="urgent-bypass",
                artifact_config=CRArtifactConfig(root_dir=Path(tmp) / "art"),
                dispatch_mode="live",
                dispatch_sink=sink,
                dispatch_state_path=state_path,
                deferred_queue_path=queue_path,
                quiet_hours_env=_env(PTILOPSIS_CR_QUIET_HOURS_ALLOW_URGENT="1"),
                now=_dt("2026-06-17T23:30:00+08:00"),
                pipeline_config=_urgent_pipeline_config(),
            )

            self.assertEqual(len(sink.submitted_messages), 1)
            self.assertEqual(_latest_receipts(result)["receipts"][0]["status"], "accepted")
            self.assertTrue(_latest_plan(result)["quiet_hours"]["bypass_applied"])
            self.assertFalse(queue_path.exists())
            state = load_cr_event_state_snapshot(state_path)
            self.assertTrue(state.loaded)
            self.assertEqual(state.snapshot.entries[0].decision_level, "urgent")

    def test_urgent_bypass_queue_cleanup_failure_is_audited(self):
        with tempfile.TemporaryDirectory() as tmp:
            queue_path = Path(tmp) / "queue.json"
            state_path = Path(tmp) / "state.json"
            build_and_write_cr_runtime_dry_run(
                hotlist_stats=_hotlist_stats("Urgent Cleanup Failure"),
                run_label="urgent-cleanup-seed",
                artifact_config=CRArtifactConfig(root_dir=Path(tmp) / "seed"),
                dispatch_mode="live",
                dispatch_sink=CRMemoryDispatchSink(),
                dispatch_state_path=state_path,
                deferred_queue_path=queue_path,
                quiet_hours_env=_env(PTILOPSIS_CR_QUIET_HOURS_ALLOW_URGENT="0"),
                now=_dt("2026-06-17T23:00:00+08:00"),
                pipeline_config=_urgent_pipeline_config(),
            )
            seeded_queue = queue_path.read_text(encoding="utf-8")
            failed_save = Mock(return_value=CRDeferredQueueSaveResult(
                saved=False,
                error="unable to save deferred queue: OSError",
                path=str(queue_path),
            ))

            with patch.dict(
                build_and_write_cr_runtime_dry_run.__globals__,
                {"save_deferred_dispatch_queue": failed_save},
            ):
                result = build_and_write_cr_runtime_dry_run(
                    hotlist_stats=_hotlist_stats("Urgent Cleanup Failure"),
                    run_label="urgent-cleanup-failure",
                    artifact_config=CRArtifactConfig(root_dir=Path(tmp) / "run"),
                    dispatch_mode="live",
                    dispatch_sink=CRMemoryDispatchSink(),
                    dispatch_state_path=state_path,
                    deferred_queue_path=queue_path,
                    quiet_hours_env=_env(
                        PTILOPSIS_CR_QUIET_HOURS_ALLOW_URGENT="1"
                    ),
                    now=_dt("2026-06-17T23:30:00+08:00"),
                    pipeline_config=_urgent_pipeline_config(),
                )

            self.assertIsNotNone(result.deferred_queue_save)
            self.assertFalse(result.deferred_queue_save.saved)
            self.assertEqual(
                _latest_receipts(result)["receipts"][0]["status"],
                "accepted",
            )
            self.assertEqual(
                _latest_plan(result)["quiet_hours"]["decision"],
                "skipped_deferred_queue_error",
            )
            self.assertEqual(queue_path.read_text(encoding="utf-8"), seeded_queue)
            state = load_cr_event_state_snapshot(state_path)
            self.assertTrue(state.loaded)
            self.assertEqual(state.snapshot.entries[0].decision_level, "urgent")

    def test_urgent_bypass_failure_is_queued_for_retry(self):
        for sink in (_RejectingSink(), _RaisingSink(), None):
            with self.subTest(sink=type(sink).__name__ if sink else "None"):
                with tempfile.TemporaryDirectory() as tmp:
                    queue_path = Path(tmp) / "queue.json"
                    state_path = Path(tmp) / "state.json"
                    result = build_and_write_cr_runtime_dry_run(
                        hotlist_stats=_hotlist_stats("Urgent Retry"),
                        run_label="urgent-retry",
                        artifact_config=CRArtifactConfig(root_dir=Path(tmp) / "art"),
                        dispatch_mode="live",
                        dispatch_sink=sink,
                        dispatch_state_path=state_path,
                        deferred_queue_path=queue_path,
                        quiet_hours_env=_env(PTILOPSIS_CR_QUIET_HOURS_ALLOW_URGENT="1"),
                        now=_dt("2026-06-17T23:30:00+08:00"),
                        pipeline_config=_urgent_pipeline_config(),
                    )
                    statuses = [r["status"] for r in _latest_receipts(result)["receipts"]]
                    self.assertIn("deferred_quiet_hours", statuses)
                    self.assertTrue(queue_path.exists())
                    self.assertFalse(state_path.exists())

    def test_artifact_and_shadow_preview_do_not_mutate_queue_or_state(self):
        for mode in ("artifact", "shadow"):
            with self.subTest(mode=mode):
                with tempfile.TemporaryDirectory() as tmp:
                    queue_path = Path(tmp) / "queue.json"
                    state_path = Path(tmp) / "state.json"
                    sink = CRMemoryDispatchSink()
                    result = build_and_write_cr_runtime_dry_run(
                        hotlist_stats=_hotlist_stats(f"Preview {mode}"),
                        run_label=f"preview-{mode}",
                        artifact_config=CRArtifactConfig(root_dir=Path(tmp) / "art"),
                        dispatch_mode=mode,
                        dispatch_sink=sink,
                        dispatch_state_path=state_path,
                        deferred_queue_path=queue_path,
                        quiet_hours_env=_env(),
                        now=_dt("2026-06-17T23:30:00+08:00"),
                        urgent_threshold=999.0,
                    )
                    self.assertEqual(sink.submitted_messages, [])
                    self.assertFalse(queue_path.exists())
                    self.assertFalse(state_path.exists())
                    self.assertTrue(_latest_plan(result)["quiet_hours"]["in_quiet_hours"])

    def test_cooldown_skipped_candidate_is_not_queued(self):
        with tempfile.TemporaryDirectory() as tmp:
            state_path = Path(tmp) / "state.json"
            queue_path = Path(tmp) / "queue.json"
            first_sink = CRMemoryDispatchSink()
            build_and_write_cr_runtime_dry_run(
                hotlist_stats=_hotlist_stats("Cooldown A"),
                run_label="cooldown-first",
                artifact_config=CRArtifactConfig(root_dir=Path(tmp) / "first"),
                dispatch_mode="live",
                dispatch_sink=first_sink,
                dispatch_state_path=state_path,
                deferred_queue_path=queue_path,
                quiet_hours_env={},
                now=_dt("2026-06-17T23:00:00+08:00"),
                urgent_threshold=999.0,
            )
            second_sink = CRMemoryDispatchSink()
            result = build_and_write_cr_runtime_dry_run(
                hotlist_stats=_hotlist_stats("Cooldown A"),
                run_label="cooldown-second",
                artifact_config=CRArtifactConfig(root_dir=Path(tmp) / "second"),
                dispatch_mode="live",
                dispatch_sink=second_sink,
                dispatch_state_path=state_path,
                deferred_queue_path=queue_path,
                quiet_hours_env=_env(),
                now=_dt("2026-06-17T23:30:00+08:00"),
                urgent_threshold=999.0,
            )
            self.assertEqual(second_sink.submitted_messages, [])
            self.assertFalse(queue_path.exists())
            statuses = [r["status"] for r in _latest_receipts(result)["receipts"]]
            self.assertIn("skipped_cooldown", statuses)

    def test_same_level_candidate_is_queued_after_cooldown_expires(self):
        with tempfile.TemporaryDirectory() as tmp:
            state_path = Path(tmp) / "state.json"
            queue_path = Path(tmp) / "queue.json"
            build_and_write_cr_runtime_dry_run(
                hotlist_stats=_hotlist_stats("Cooldown Expired"),
                run_label="cooldown-expired-first",
                artifact_config=CRArtifactConfig(root_dir=Path(tmp) / "first"),
                dispatch_mode="live",
                dispatch_sink=CRMemoryDispatchSink(),
                dispatch_state_path=state_path,
                deferred_queue_path=queue_path,
                quiet_hours_env={},
                now=_dt("2026-06-17T22:00:00+08:00"),
                urgent_threshold=999.0,
            )

            result = build_and_write_cr_runtime_dry_run(
                hotlist_stats=_hotlist_stats("Cooldown Expired"),
                run_label="cooldown-expired-second",
                artifact_config=CRArtifactConfig(root_dir=Path(tmp) / "second"),
                dispatch_mode="live",
                dispatch_sink=CRMemoryDispatchSink(),
                dispatch_state_path=state_path,
                deferred_queue_path=queue_path,
                quiet_hours_env=_env(),
                now=_dt("2026-06-17T23:30:00+08:00"),
                urgent_threshold=999.0,
            )

            receipts = _latest_receipts(result)["receipts"]
            self.assertEqual(receipts[0]["status"], "deferred_quiet_hours")
            self.assertEqual(receipts[0]["deferred_upsert_outcome"], "inserted")
            queue = json.loads(queue_path.read_text(encoding="utf-8"))
            self.assertEqual(len(queue["entries"]), 1)

    def test_all_candidates_skipped_reports_zero_deferred_count(self):
        with tempfile.TemporaryDirectory() as tmp:
            queue_path = Path(tmp) / "queue.json"
            build_and_write_cr_runtime_dry_run(
                hotlist_stats=_hotlist_stats("Queued Higher Level"),
                run_label="all-skipped-seed",
                artifact_config=CRArtifactConfig(root_dir=Path(tmp) / "seed"),
                dispatch_mode="live",
                dispatch_sink=CRMemoryDispatchSink(),
                deferred_queue_path=queue_path,
                quiet_hours_env=_env(PTILOPSIS_CR_QUIET_HOURS_ALLOW_URGENT="0"),
                now=_dt("2026-06-17T23:00:00+08:00"),
                pipeline_config=_urgent_pipeline_config(),
            )

            result = build_and_write_cr_runtime_dry_run(
                hotlist_stats=_hotlist_stats("Queued Higher Level"),
                run_label="all-skipped-alert",
                artifact_config=CRArtifactConfig(root_dir=Path(tmp) / "run"),
                dispatch_mode="live",
                dispatch_sink=CRMemoryDispatchSink(),
                deferred_queue_path=queue_path,
                quiet_hours_env=_env(),
                now=_dt("2026-06-17T23:30:00+08:00"),
                urgent_threshold=999.0,
            )

            receipt = _latest_receipts(result)["receipts"][0]
            self.assertEqual(receipt["status"], "skipped_deferred_queue_upsert")
            self.assertEqual(
                receipt["deferred_upsert_reason"],
                "existing_higher_level",
            )
            plan = _latest_plan(result)
            self.assertEqual(plan["decision"], "suppress")
            self.assertEqual(
                plan["quiet_hours"]["decision"],
                "skipped_deferred_queue_upsert",
            )
            self.assertEqual(plan["quiet_hours"]["deferred_count"], 0)

    def test_queue_save_failure_never_emits_deferred_receipt(self):
        with tempfile.TemporaryDirectory() as tmp:
            queue_path = Path(tmp) / "queue.json"
            failed_save = Mock(return_value=CRDeferredQueueSaveResult(
                saved=False,
                error="unable to save deferred queue: OSError",
                path=str(queue_path),
            ))
            with patch.dict(
                build_and_write_cr_runtime_dry_run.__globals__,
                {"save_deferred_dispatch_queue": failed_save},
            ):
                result = build_and_write_cr_runtime_dry_run(
                    hotlist_stats=_hotlist_stats("Queue Save Failure"),
                    run_label="queue-save-failure",
                    artifact_config=CRArtifactConfig(root_dir=Path(tmp) / "art"),
                    dispatch_mode="live",
                    dispatch_sink=CRMemoryDispatchSink(),
                    deferred_queue_path=queue_path,
                    quiet_hours_env=_env(),
                    now=_dt("2026-06-17T23:30:00+08:00"),
                    urgent_threshold=999.0,
                )

            receipts = _latest_receipts(result)["receipts"]
            self.assertEqual(receipts[0]["status"], "skipped_deferred_queue_error")
            self.assertEqual(receipts[0]["detail"], "deferred_queue_save_failed")
            self.assertFalse(queue_path.exists())


if __name__ == "__main__":
    unittest.main()
