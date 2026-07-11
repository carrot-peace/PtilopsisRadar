# coding=utf-8
"""
PR-CR-A3: CR dispatch receipt JSON serialization + artifact writing tests.

Covers:
  - Serialization: schema_version, run_id, created_at, dispatch_mode,
    plan_decision, plan_should_dispatch, receipts list, status vocabulary
  - Artifact writing: latest + archive dispatch_receipts.json, JSON validity,
    parity between latest and archive, existing artifacts still work
  - Mode behavior: artifact -> not_executed, shadow -> shadow_only,
    live without Telegram gate -> not_configured
  - Plan behavior: no candidate -> skipped_no_candidate,
    suppress -> skipped_suppress, dispatch-ready -> mode-dependent
  - Transport behavior: fake accepted sink -> accepted,
    fake rejected sink -> rejected, fake raising sink -> failed_transport
  - Boundary: no forbidden tokens in dispatch_receipt.py

Pure tests only — no network, no Telegram, no real output directories.
"""

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

# Ensure project root is on path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from trendradar.cr.artifacts import CRArtifactConfig
from trendradar.cr.dispatch_executor import (
    CRDispatchReceipt,
    CRDispatchSink,
    CRMemoryDispatchSink,
)
from trendradar.cr.dispatch_plan import (
    CRDispatchMessage,
    CRDispatchPlan,
    DECISION_DISPATCH,
    DECISION_NO_CANDIDATE,
    DECISION_SUPPRESSED,
    DISPATCH_PLAN_SCHEMA_VERSION,
)
from trendradar.cr.dispatch_receipt import (
    DISPATCH_RECEIPT_SCHEMA_VERSION,
    STATUS_ACCEPTED,
    STATUS_FAILED_TRANSPORT,
    STATUS_NOT_CONFIGURED,
    STATUS_NOT_EXECUTED,
    STATUS_REJECTED,
    STATUS_SHADOW_ONLY,
    STATUS_SKIPPED_DEFERRED_QUEUE_UPSERT,
    STATUS_SKIPPED_NO_CANDIDATE,
    STATUS_SKIPPED_SUPPRESS,
    build_dispatch_receipts_json,
)
from trendradar.cr.runtime_dry_run import build_and_write_cr_runtime_dry_run


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _make_message(
    text: str = "CR-A body",
    candidate_count: int = 1,
    run_label: str = "run-x",
) -> CRDispatchMessage:
    return CRDispatchMessage(
        text=text,
        format="plain_text",
        candidate_count=candidate_count,
        run_label=run_label,
        urgent_count=0,
        high_score_suppressed_count=0,
    )


def _make_ready_plan(
    messages: tuple[CRDispatchMessage, ...] | None = None,
    run_label: str = "run-x",
) -> CRDispatchPlan:
    if messages is None:
        messages = (_make_message(run_label=run_label),)
    first = messages[0]
    return CRDispatchPlan(
        should_dispatch=True,
        messages=messages,
        reason="ready",
        run_label=run_label,
        candidate_count=first.candidate_count,
        urgent_count=0,
        high_score_suppressed_count=0,
    )


def _make_skipped_plan(
    reason: str = "no_selected_candidates",
    run_label: str = "run-x",
) -> CRDispatchPlan:
    return CRDispatchPlan(
        should_dispatch=False,
        messages=(),
        reason=reason,
        run_label=run_label,
        candidate_count=0,
        urgent_count=0,
        high_score_suppressed_count=0,
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


class _RejectingSink:
    """Sink that rejects every message."""

    def submit(self, message, *, message_index):
        return CRDispatchReceipt(
            message_index=message_index,
            accepted=False,
            status="rejected",
            detail="telegram_rejected",
            candidate_count=message.candidate_count,
            run_label=message.run_label,
        )


class _RaisingSink:
    """Sink that raises a transport exception on submit."""

    def submit(self, message, *, message_index):
        raise TimeoutError("connection timed out")


# ---------------------------------------------------------------------------
# Test Group A — Serialization: schema_version
# ---------------------------------------------------------------------------


class TestSchemaVersion(unittest.TestCase):
    def test_schema_version_present(self):
        plan = _make_skipped_plan()
        d = build_dispatch_receipts_json(plan, dispatch_mode="artifact")
        self.assertEqual(d["schema_version"], DISPATCH_RECEIPT_SCHEMA_VERSION)

    def test_schema_version_is_string(self):
        plan = _make_skipped_plan()
        d = build_dispatch_receipts_json(plan, dispatch_mode="artifact")
        self.assertIsInstance(d["schema_version"], str)


# ---------------------------------------------------------------------------
# Test Group B — Serialization: run_id + created_at + dispatch_mode
# ---------------------------------------------------------------------------


class TestRunMetadata(unittest.TestCase):
    def test_run_id_matches_run_label(self):
        plan = _make_skipped_plan(run_label="run-20260617-090000")
        d = build_dispatch_receipts_json(plan, dispatch_mode="artifact")
        self.assertEqual(d["run_id"], "run-20260617-090000")

    def test_created_at_from_parameter(self):
        plan = _make_skipped_plan()
        d = build_dispatch_receipts_json(
            plan, dispatch_mode="artifact", created_at="2026-06-17T09:00:00+08:00"
        )
        self.assertEqual(d["created_at"], "2026-06-17T09:00:00+08:00")

    def test_created_at_none_by_default(self):
        plan = _make_skipped_plan()
        d = build_dispatch_receipts_json(plan, dispatch_mode="artifact")
        self.assertIsNone(d["created_at"])

    def test_dispatch_mode_present(self):
        plan = _make_skipped_plan()
        for mode in ("artifact", "shadow", "live"):
            d = build_dispatch_receipts_json(plan, dispatch_mode=mode)
            self.assertEqual(d["dispatch_mode"], mode)


# ---------------------------------------------------------------------------
# Test Group C — Serialization: plan_decision + plan_should_dispatch
# ---------------------------------------------------------------------------


class TestPlanFields(unittest.TestCase):
    def test_plan_decision_no_candidate(self):
        plan = _make_skipped_plan(reason="no_selected_candidates")
        d = build_dispatch_receipts_json(plan, dispatch_mode="artifact")
        self.assertEqual(d["plan_decision"], DECISION_NO_CANDIDATE)
        self.assertFalse(d["plan_should_dispatch"])

    def test_plan_decision_suppress(self):
        plan = _make_skipped_plan(reason="empty_text")
        d = build_dispatch_receipts_json(plan, dispatch_mode="artifact")
        self.assertEqual(d["plan_decision"], DECISION_SUPPRESSED)
        self.assertFalse(d["plan_should_dispatch"])

    def test_deferred_queue_upsert_skip_maps_to_suppressed_receipt(self):
        plan = _make_skipped_plan(reason="skipped_deferred_queue_upsert")

        data = build_dispatch_receipts_json(plan, dispatch_mode="live")

        self.assertEqual(data["plan_decision"], DECISION_SUPPRESSED)
        self.assertEqual(
            data["receipts"][0]["status"],
            STATUS_SKIPPED_DEFERRED_QUEUE_UPSERT,
        )
        self.assertEqual(
            data["receipts"][0]["detail"],
            "deferred_queue_upsert_rejected",
        )

    def test_plan_decision_dispatch(self):
        plan = _make_ready_plan()
        d = build_dispatch_receipts_json(plan, dispatch_mode="live")
        self.assertEqual(d["plan_decision"], DECISION_DISPATCH)
        self.assertTrue(d["plan_should_dispatch"])


# ---------------------------------------------------------------------------
# Test Group D — Mode behavior: artifact / shadow
# ---------------------------------------------------------------------------


class TestArtifactMode(unittest.TestCase):
    def test_artifact_not_executed(self):
        plan = _make_ready_plan()
        d = build_dispatch_receipts_json(plan, dispatch_mode="artifact")
        self.assertEqual(len(d["receipts"]), 1)
        r = d["receipts"][0]
        self.assertEqual(r["status"], STATUS_NOT_EXECUTED)
        self.assertFalse(r["attempted"])
        self.assertFalse(r["accepted"])
        self.assertEqual(r["detail"], "artifact_mode_no_send")

    def test_artifact_skipped_plan(self):
        plan = _make_skipped_plan(reason="no_selected_candidates")
        d = build_dispatch_receipts_json(plan, dispatch_mode="artifact")
        self.assertEqual(len(d["receipts"]), 1)
        r = d["receipts"][0]
        self.assertEqual(r["status"], STATUS_NOT_EXECUTED)
        self.assertFalse(r["attempted"])


class TestShadowMode(unittest.TestCase):
    def test_shadow_shadow_only(self):
        plan = _make_ready_plan()
        d = build_dispatch_receipts_json(plan, dispatch_mode="shadow")
        self.assertEqual(len(d["receipts"]), 1)
        r = d["receipts"][0]
        self.assertEqual(r["status"], STATUS_SHADOW_ONLY)
        self.assertFalse(r["attempted"])
        self.assertFalse(r["accepted"])
        self.assertEqual(r["detail"], "shadow_mode_no_send")

    def test_shadow_skipped_plan(self):
        plan = _make_skipped_plan(reason="empty_text")
        d = build_dispatch_receipts_json(plan, dispatch_mode="shadow")
        self.assertEqual(len(d["receipts"]), 1)
        r = d["receipts"][0]
        self.assertEqual(r["status"], STATUS_SHADOW_ONLY)


# ---------------------------------------------------------------------------
# Test Group E — Plan behavior: no candidate / suppress
# ---------------------------------------------------------------------------


class TestPlanBehavior(unittest.TestCase):
    def test_no_candidate_skipped(self):
        plan = _make_skipped_plan(reason="no_selected_candidates")
        d = build_dispatch_receipts_json(plan, dispatch_mode="live")
        self.assertEqual(len(d["receipts"]), 1)
        r = d["receipts"][0]
        self.assertEqual(r["status"], STATUS_SKIPPED_NO_CANDIDATE)
        self.assertFalse(r["attempted"])
        self.assertFalse(r["accepted"])

    def test_suppress_skipped(self):
        plan = _make_skipped_plan(reason="empty_text")
        d = build_dispatch_receipts_json(plan, dispatch_mode="live")
        self.assertEqual(len(d["receipts"]), 1)
        r = d["receipts"][0]
        self.assertEqual(r["status"], STATUS_SKIPPED_SUPPRESS)
        self.assertFalse(r["attempted"])


# ---------------------------------------------------------------------------
# Test Group F — Live mode: no sink configured
# ---------------------------------------------------------------------------


class TestLiveNoSink(unittest.TestCase):
    def test_live_no_sink_not_configured(self):
        plan = _make_ready_plan()
        d = build_dispatch_receipts_json(
            plan, dispatch_mode="live", execution=None
        )
        self.assertEqual(len(d["receipts"]), 1)
        r = d["receipts"][0]
        self.assertEqual(r["status"], STATUS_NOT_CONFIGURED)
        self.assertFalse(r["attempted"])
        self.assertEqual(r["detail"], "no_sink_configured")


# ---------------------------------------------------------------------------
# Test Group G — Transport behavior: accepted / rejected / failed
# ---------------------------------------------------------------------------


class TestTransportAccepted(unittest.TestCase):
    def test_accepted_sink(self):
        plan = _make_ready_plan()
        sink = CRMemoryDispatchSink()
        from trendradar.cr.dispatch_executor import execute_cr_dispatch_plan

        execution = execute_cr_dispatch_plan(plan, sink=sink)
        d = build_dispatch_receipts_json(
            plan, dispatch_mode="live", execution=execution
        )
        self.assertEqual(len(d["receipts"]), 1)
        r = d["receipts"][0]
        self.assertEqual(r["status"], STATUS_ACCEPTED)
        self.assertTrue(r["attempted"])
        self.assertTrue(r["accepted"])


class TestTransportRejected(unittest.TestCase):
    def test_rejected_sink(self):
        plan = _make_ready_plan()
        sink = _RejectingSink()
        from trendradar.cr.dispatch_executor import execute_cr_dispatch_plan

        execution = execute_cr_dispatch_plan(plan, sink=sink)
        d = build_dispatch_receipts_json(
            plan, dispatch_mode="live", execution=execution
        )
        self.assertEqual(len(d["receipts"]), 1)
        r = d["receipts"][0]
        self.assertEqual(r["status"], STATUS_REJECTED)
        self.assertTrue(r["attempted"])
        self.assertFalse(r["accepted"])


class TestTransportFailed(unittest.TestCase):
    def test_raising_sink_produces_failed_transport(self):
        plan = _make_ready_plan()
        sink = _RaisingSink()
        from trendradar.cr.dispatch_executor import execute_cr_dispatch_plan

        execution = execute_cr_dispatch_plan(plan, sink=sink)
        d = build_dispatch_receipts_json(
            plan, dispatch_mode="live", execution=execution
        )
        self.assertEqual(len(d["receipts"]), 1)
        r = d["receipts"][0]
        self.assertEqual(r["status"], STATUS_FAILED_TRANSPORT)
        self.assertTrue(r["attempted"])
        self.assertFalse(r["accepted"])
        self.assertEqual(r["detail"], "TimeoutError")


# ---------------------------------------------------------------------------
# Test Group H — Receipt entry fields
# ---------------------------------------------------------------------------


class TestReceiptEntryFields(unittest.TestCase):
    def test_entry_has_all_expected_keys(self):
        plan = _make_skipped_plan()
        d = build_dispatch_receipts_json(plan, dispatch_mode="artifact")
        r = d["receipts"][0]
        expected_keys = {
            "message_index",
            "attempted",
            "accepted",
            "status",
            "detail",
            "transport",
            "http_status",
            "sink_ok",
            "exception_type",
            "exception_message",
        }
        self.assertEqual(set(r.keys()), expected_keys)

    def test_null_fields_for_skipped(self):
        plan = _make_skipped_plan()
        d = build_dispatch_receipts_json(plan, dispatch_mode="artifact")
        r = d["receipts"][0]
        self.assertIsNone(r["transport"])
        self.assertIsNone(r["http_status"])
        self.assertIsNone(r["sink_ok"])
        self.assertIsNone(r["exception_type"])
        self.assertIsNone(r["exception_message"])


# ---------------------------------------------------------------------------
# Test Group I — JSON round-trip
# ---------------------------------------------------------------------------


class TestJsonRoundTrip(unittest.TestCase):
    def test_dict_is_json_serializable(self):
        plan = _make_ready_plan()
        d = build_dispatch_receipts_json(
            plan,
            dispatch_mode="live",
            created_at="2026-06-17T09:00:00",
        )
        serialized = json.dumps(d, ensure_ascii=False)
        parsed = json.loads(serialized)
        self.assertEqual(parsed["schema_version"], DISPATCH_RECEIPT_SCHEMA_VERSION)
        self.assertEqual(parsed["dispatch_mode"], "live")
        self.assertIsInstance(parsed["receipts"], list)


# ---------------------------------------------------------------------------
# Test Group J — Artifact writing
# ---------------------------------------------------------------------------


class TestArtifactWriting(unittest.TestCase):
    def _run(self, tmp, *, hotlist=None, dispatch_mode="artifact"):
        return build_and_write_cr_runtime_dry_run(
            hotlist_stats=hotlist or _hotlist_stats(),
            run_label="run-j",
            artifact_config=CRArtifactConfig(root_dir=Path(tmp)),
            dispatch_mode=dispatch_mode,
        )

    def test_writes_dispatch_receipt_json_latest(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = self._run(tmp)
            self.assertTrue(
                result.dispatch_receipt_json_paths.dispatch_receipt_latest_path.exists()
            )

    def test_writes_dispatch_receipt_json_archive(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = self._run(tmp)
            self.assertTrue(
                result.dispatch_receipt_json_paths.dispatch_receipt_archive_path.exists()
            )

    def test_dispatch_receipt_json_is_valid_json(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = self._run(tmp)
            path = result.dispatch_receipt_json_paths.dispatch_receipt_latest_path
            data = json.loads(path.read_text(encoding="utf-8"))
            self.assertIsInstance(data, dict)

    def test_dispatch_receipt_json_has_schema_version(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = self._run(tmp)
            path = result.dispatch_receipt_json_paths.dispatch_receipt_latest_path
            data = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(data["schema_version"], DISPATCH_RECEIPT_SCHEMA_VERSION)

    def test_latest_and_archive_contain_same_data(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = self._run(tmp)
            latest = json.loads(
                result.dispatch_receipt_json_paths.dispatch_receipt_latest_path.read_text(
                    encoding="utf-8"
                )
            )
            archive = json.loads(
                result.dispatch_receipt_json_paths.dispatch_receipt_archive_path.read_text(
                    encoding="utf-8"
                )
            )
            self.assertEqual(latest, archive)

    def test_dispatch_plan_json_still_written(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = self._run(tmp)
            self.assertTrue(
                result.dispatch_plan_json_paths.dispatch_plan_latest_path.exists()
            )

    def test_markdown_html_still_written(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = self._run(tmp)
            self.assertTrue(result.artifact_paths.latest_markdown_path.exists())
            self.assertTrue(result.artifact_paths.latest_html_path.exists())


# ---------------------------------------------------------------------------
# Test Group K — Mode behavior via runtime
# ---------------------------------------------------------------------------


class TestModeBehaviorRuntime(unittest.TestCase):
    def test_artifact_mode_receipt_not_executed(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = build_and_write_cr_runtime_dry_run(
                hotlist_stats=_hotlist_stats(),
                run_label="mode-art",
                artifact_config=CRArtifactConfig(root_dir=Path(tmp)),
                dispatch_mode="artifact",
            )
            path = result.dispatch_receipt_json_paths.dispatch_receipt_latest_path
            data = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(data["dispatch_mode"], "artifact")
            self.assertTrue(
                all(r["status"] == STATUS_NOT_EXECUTED for r in data["receipts"])
            )

    def test_shadow_mode_receipt_shadow_only(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = build_and_write_cr_runtime_dry_run(
                hotlist_stats=_hotlist_stats(),
                run_label="mode-shd",
                artifact_config=CRArtifactConfig(root_dir=Path(tmp)),
                dispatch_mode="shadow",
            )
            path = result.dispatch_receipt_json_paths.dispatch_receipt_latest_path
            data = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(data["dispatch_mode"], "shadow")
            self.assertTrue(
                all(r["status"] == STATUS_SHADOW_ONLY for r in data["receipts"])
            )

    def test_live_empty_pipeline_skipped(self):
        """Empty pipeline in live mode produces skipped_no_candidate."""
        with tempfile.TemporaryDirectory() as tmp:
            result = build_and_write_cr_runtime_dry_run(
                run_label="mode-live",
                artifact_config=CRArtifactConfig(root_dir=Path(tmp)),
                dispatch_mode="live",
                dispatch_sink=None,
            )
            path = result.dispatch_receipt_json_paths.dispatch_receipt_latest_path
            data = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(data["dispatch_mode"], "live")
            self.assertFalse(data["plan_should_dispatch"])
            r = data["receipts"][0]
            self.assertEqual(r["status"], STATUS_SKIPPED_NO_CANDIDATE)

    def test_receipt_json_written_for_all_modes(self):
        """Receipt JSON is written regardless of mode."""
        for mode in ("artifact", "shadow", "live"):
            with tempfile.TemporaryDirectory() as tmp:
                result = build_and_write_cr_runtime_dry_run(
                    hotlist_stats=_hotlist_stats(),
                    run_label=f"mode-{mode}",
                    artifact_config=CRArtifactConfig(root_dir=Path(tmp)),
                    dispatch_mode=mode,
                )
                path = result.dispatch_receipt_json_paths.dispatch_receipt_latest_path
                self.assertTrue(path.exists())
                data = json.loads(path.read_text(encoding="utf-8"))
                self.assertEqual(data["dispatch_mode"], mode)


# ---------------------------------------------------------------------------
# Test Group L — Empty pipeline
# ---------------------------------------------------------------------------


class TestEmptyPipeline(unittest.TestCase):
    def test_empty_pipeline_receipt(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = build_and_write_cr_runtime_dry_run(
                run_label="empty",
                artifact_config=CRArtifactConfig(root_dir=Path(tmp)),
                dispatch_mode="artifact",
            )
            path = result.dispatch_receipt_json_paths.dispatch_receipt_latest_path
            data = json.loads(path.read_text(encoding="utf-8"))
            self.assertFalse(data["plan_should_dispatch"])
            r = data["receipts"][0]
            self.assertEqual(r["status"], STATUS_NOT_EXECUTED)


# ---------------------------------------------------------------------------
# Test Group M — Boundary
# ---------------------------------------------------------------------------


class TestSourceBoundary(unittest.TestCase):
    """dispatch_receipt.py must not reference forbidden subsystems."""

    FORBIDDEN = (
        "trendradar.notification",
        "trendradar.storage",
        "trendradar.config",
        "trendradar.ai",
        "AIAnalysisResult",
        "chat_id",
        "bot_token",
        "sender",
        "dispatcher",
    )

    def test_no_forbidden_tokens_in_dispatch_receipt(self):
        import trendradar.cr.dispatch_receipt as mod

        source = Path(mod.__file__).read_text(encoding="utf-8")
        for token in self.FORBIDDEN:
            self.assertNotIn(
                token, source, f"forbidden token {token!r} present in module"
            )


if __name__ == "__main__":
    unittest.main()
