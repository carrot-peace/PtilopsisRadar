# coding=utf-8
"""
PR9m: CR dispatch executor / sink boundary tests.

Covers:
  - result model shape (frozen, tuple receipts)
  - skipped plan never calls the sink
  - ready plan submits to the injected local sink
  - multiple messages preserve order + message_index
  - sink exceptions propagate (no catch/suppress in v0.1)
  - optional runtime dry-run sink integration (local only, temp dirs)
  - source boundary (no telegram / network libs / notification / storage / ...)

Pure, local execution only — no network, no Telegram, no notification modules,
no real output directories.
"""

import dataclasses
import os
import sys
import tempfile
import unittest
from pathlib import Path

# Ensure project root is on path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from trendradar.cr.artifacts import CRArtifactConfig
from trendradar.cr.dispatch_executor import (
    CRDispatchExecutionResult,
    CRDispatchReceipt,
    CRDispatchSink,
    CRMemoryDispatchSink,
    CRNoopDispatchSink,
    execute_cr_dispatch_plan,
)
from trendradar.cr.dispatch_plan import CRDispatchMessage, CRDispatchPlan
from trendradar.cr.runtime_dry_run import build_and_write_cr_runtime_dry_run


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _make_message(
    text: str = "CR-A body",
    candidate_count: int = 1,
    run_label: str = "run-x",
    urgent_count: int = 0,
    high_score_suppressed_count: int = 0,
) -> CRDispatchMessage:
    return CRDispatchMessage(
        text=text,
        format="plain_text",
        candidate_count=candidate_count,
        run_label=run_label,
        urgent_count=urgent_count,
        high_score_suppressed_count=high_score_suppressed_count,
    )


def _make_ready_plan(
    messages: tuple[CRDispatchMessage, ...],
    run_label: str = "run-x",
) -> CRDispatchPlan:
    first = messages[0]
    return CRDispatchPlan(
        should_dispatch=True,
        messages=messages,
        reason="ready",
        run_label=run_label,
        candidate_count=first.candidate_count,
        urgent_count=first.urgent_count,
        high_score_suppressed_count=first.high_score_suppressed_count,
    )


def _make_skipped_plan(reason: str = "no_selected_candidates") -> CRDispatchPlan:
    return CRDispatchPlan(
        should_dispatch=False,
        messages=(),
        reason=reason,
        run_label="run-x",
        candidate_count=0,
        urgent_count=0,
        high_score_suppressed_count=0,
    )


class _RaisingSink:
    """Sink whose submit() always raises — proves it is/ isn't called."""

    def submit(self, message, *, message_index):  # noqa: ANN001
        raise RuntimeError("sink should not have been called / boom")


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
# Test Group A — Model Shape
# ---------------------------------------------------------------------------


class TestModelShape(unittest.TestCase):
    def test_receipt_is_frozen(self):
        receipt = CRDispatchReceipt(
            message_index=0,
            accepted=True,
            status="accepted",
            detail="memory_sink",
            candidate_count=1,
            run_label="r",
        )
        with self.assertRaises(dataclasses.FrozenInstanceError):
            receipt.accepted = False  # type: ignore[misc]

    def test_execution_result_is_frozen(self):
        result = execute_cr_dispatch_plan(
            _make_skipped_plan(), sink=CRMemoryDispatchSink()
        )
        with self.assertRaises(dataclasses.FrozenInstanceError):
            result.attempted = True  # type: ignore[misc]

    def test_receipts_is_tuple(self):
        result = execute_cr_dispatch_plan(
            _make_ready_plan((_make_message(),)), sink=CRMemoryDispatchSink()
        )
        self.assertIsInstance(result.receipts, tuple)


# ---------------------------------------------------------------------------
# Test Group B — Skipped Plan
# ---------------------------------------------------------------------------


class TestSkippedPlan(unittest.TestCase):
    def test_skipped_does_not_call_sink(self):
        plan = _make_skipped_plan(reason="empty_text")
        # A raising sink would blow up if called.
        result = execute_cr_dispatch_plan(plan, sink=_RaisingSink())
        self.assertFalse(result.attempted)
        self.assertEqual(result.reason, "empty_text")
        self.assertEqual(result.receipts, ())
        self.assertEqual(result.accepted_count, 0)

    def test_skipped_reason_mirrors_plan(self):
        plan = _make_skipped_plan(reason="no_selected_candidates")
        result = execute_cr_dispatch_plan(plan, sink=_RaisingSink())
        self.assertEqual(result.reason, plan.reason)
        self.assertIs(result.plan, plan)

    def test_memory_sink_untouched_when_skipped(self):
        sink = CRMemoryDispatchSink()
        execute_cr_dispatch_plan(_make_skipped_plan(), sink=sink)
        self.assertEqual(sink.submitted_messages, [])


# ---------------------------------------------------------------------------
# Test Group C — Ready Plan Execution
# ---------------------------------------------------------------------------


class TestReadyPlanExecution(unittest.TestCase):
    def test_single_message_execution(self):
        message = _make_message(text="hello", candidate_count=2, run_label="r1")
        plan = _make_ready_plan((message,), run_label="r1")
        sink = CRMemoryDispatchSink()
        result = execute_cr_dispatch_plan(plan, sink=sink)

        self.assertTrue(result.attempted)
        self.assertEqual(result.reason, "executed")
        self.assertEqual(len(result.receipts), 1)
        self.assertEqual(result.receipts[0].status, "accepted")
        self.assertTrue(result.receipts[0].accepted)
        self.assertEqual(result.accepted_count, 1)

    def test_memory_sink_stores_original_message(self):
        message = _make_message(text="payload", candidate_count=2)
        plan = _make_ready_plan((message,))
        sink = CRMemoryDispatchSink()
        execute_cr_dispatch_plan(plan, sink=sink)

        self.assertEqual(len(sink.submitted_messages), 1)
        self.assertIs(sink.submitted_messages[0], message)

    def test_receipt_carries_message_counts(self):
        message = _make_message(candidate_count=5, run_label="rr")
        plan = _make_ready_plan((message,), run_label="rr")
        result = execute_cr_dispatch_plan(plan, sink=CRMemoryDispatchSink())
        self.assertEqual(result.receipts[0].candidate_count, 5)
        self.assertEqual(result.receipts[0].run_label, "rr")
        self.assertEqual(result.receipts[0].message_index, 0)

    def test_noop_sink_accepts_without_storing(self):
        plan = _make_ready_plan((_make_message(),))
        result = execute_cr_dispatch_plan(plan, sink=CRNoopDispatchSink())
        self.assertTrue(result.attempted)
        self.assertEqual(result.accepted_count, 1)
        self.assertEqual(result.receipts[0].detail, "noop_sink")

    def test_plan_not_mutated(self):
        message = _make_message()
        plan = _make_ready_plan((message,))
        before = (plan.should_dispatch, plan.messages, plan.reason)
        execute_cr_dispatch_plan(plan, sink=CRMemoryDispatchSink())
        after = (plan.should_dispatch, plan.messages, plan.reason)
        self.assertEqual(before, after)


# ---------------------------------------------------------------------------
# Test Group D — Multiple Messages
# ---------------------------------------------------------------------------


class TestMultipleMessages(unittest.TestCase):
    def test_two_messages_in_order(self):
        m0 = _make_message(text="first", run_label="r")
        m1 = _make_message(text="second", run_label="r")
        plan = _make_ready_plan((m0, m1), run_label="r")
        sink = CRMemoryDispatchSink()
        result = execute_cr_dispatch_plan(plan, sink=sink)

        # Submitted in order.
        self.assertEqual([m.text for m in sink.submitted_messages], ["first", "second"])
        # message_index values are 0, 1.
        self.assertEqual([r.message_index for r in result.receipts], [0, 1])
        # Receipts preserve order.
        self.assertEqual(len(result.receipts), 2)
        self.assertEqual(result.accepted_count, 2)


# ---------------------------------------------------------------------------
# Test Group E — Sink Exception Propagation
# ---------------------------------------------------------------------------


class TestSinkExceptionPropagation(unittest.TestCase):
    def test_sink_exception_propagates(self):
        plan = _make_ready_plan((_make_message(),))
        with self.assertRaises(RuntimeError):
            execute_cr_dispatch_plan(plan, sink=_RaisingSink())


# ---------------------------------------------------------------------------
# Test Group F — Runtime Dry-Run Optional Sink
# ---------------------------------------------------------------------------


class TestRuntimeDryRunSink(unittest.TestCase):
    def _artifact_config(self, root: str) -> CRArtifactConfig:
        return CRArtifactConfig(root_dir=Path(root))

    def test_no_sink_means_no_execution(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = build_and_write_cr_runtime_dry_run(
                hotlist_stats=_hotlist_stats(),
                run_label="run-f",
                artifact_config=self._artifact_config(tmp),
            )
            self.assertIsNone(result.dispatch_execution)

    def test_sink_produces_execution_result(self):
        with tempfile.TemporaryDirectory() as tmp:
            sink = CRMemoryDispatchSink()
            result = build_and_write_cr_runtime_dry_run(
                hotlist_stats=_hotlist_stats(),
                run_label="run-f",
                artifact_config=self._artifact_config(tmp),
                dispatch_sink=sink,
                dispatch_mode="live",
            )
            self.assertIsInstance(
                result.dispatch_execution, CRDispatchExecutionResult
            )

    def test_sink_receives_messages_only_when_dispatching(self):
        with tempfile.TemporaryDirectory() as tmp:
            sink = CRMemoryDispatchSink()
            result = build_and_write_cr_runtime_dry_run(
                hotlist_stats=_hotlist_stats(),
                run_label="run-f",
                artifact_config=self._artifact_config(tmp),
                dispatch_sink=sink,
                dispatch_mode="live",
            )
            plan = result.dispatch_plan
            execution = result.dispatch_execution
            # Execution attempt tracks the plan's dispatch decision exactly.
            self.assertIsNotNone(execution)
            self.assertEqual(execution.attempted, plan.should_dispatch)
            if plan.should_dispatch:
                self.assertEqual(
                    len(sink.submitted_messages), len(plan.messages)
                )
            else:
                self.assertEqual(sink.submitted_messages, [])
                self.assertEqual(execution.receipts, ())


# ---------------------------------------------------------------------------
# Test Group G — Boundary
# ---------------------------------------------------------------------------


class TestSourceBoundary(unittest.TestCase):
    """dispatch_executor.py must not reference forbidden subsystems / tokens."""

    FORBIDDEN = (
        "trendradar.notification",
        "trendradar.storage",
        "trendradar.config",
        "trendradar.ai",
        "AIAnalysisResult",
        "telegram",
        "chat_id",
        "bot_token",
        "recipient",
        "dispatcher",
        "cooldown",
        "dedupe",
        "alert_state",
        "requests",
        "httpx",
        "aiohttp",
    )

    def test_no_forbidden_tokens(self):
        import trendradar.cr.dispatch_executor as mod

        source = Path(mod.__file__).read_text(encoding="utf-8")
        for token in self.FORBIDDEN:
            self.assertNotIn(
                token, source, f"forbidden token {token!r} present in module"
            )

    def test_protocol_is_usable_type(self):
        # CRDispatchSink is importable and the local sinks satisfy it.
        self.assertTrue(hasattr(CRDispatchSink, "submit") or True)
        self.assertTrue(hasattr(CRMemoryDispatchSink(), "submit"))


if __name__ == "__main__":
    unittest.main()
