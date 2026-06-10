# coding=utf-8
"""
PR9l: CR-A dispatch plan tests.

Covers:
  - model shape (frozen, tuple messages, plain_text format)
  - ready plan semantics + message field mirroring
  - no-selected-candidates blocking
  - empty-text guard (allow_empty_text False / True)
  - min_candidate_count threshold behavior
  - source boundary (no notification / storage / config / ai / telegram /
    chat_id / bot_token / sender / dispatcher / cooldown / dedupe / alert_state)

Pure planning only — no network, no Telegram, no notification modules, no
real output directories.
"""

import dataclasses
import os
import sys
import unittest
from pathlib import Path

# Ensure project root is on path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from trendradar.cr.decision import (
    CRDecision,
    DECISION_ALERT,
    DECISION_URGENT,
)
from trendradar.cr.dispatch_plan import (
    CRDispatchMessage,
    CRDispatchPlan,
    build_cr_a_dispatch_plan,
)
from trendradar.cr.models import CRCandidate
from trendradar.cr.pipeline import (
    CRPipelineResult,
    build_cr_pipeline_from_primitives,
)
from trendradar.cr.presentation import CRPresentedCandidate
from trendradar.cr.scoring import CRScoreResult


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _make_presented(
    candidate_id: str = "c1",
    cluster_key: str = "key1",
    display_title: str = "Topic A",
    representative_url: str | None = "https://example.com",
    decision_level: str = DECISION_ALERT,
    total_score: float = 70.0,
) -> CRPresentedCandidate:
    cand = CRCandidate(
        candidate_id=candidate_id,
        cluster_key=cluster_key,
        display_title=display_title,
        representative_url=representative_url,
        source_items=[],
    )
    sr = CRScoreResult(
        candidate_id=candidate_id,
        cluster_key=cluster_key,
        profile_version="cr-score-v0.1",
        total_score=total_score,
        trigger_reasons=[],
        debug={},
    )
    dec = CRDecision(
        candidate_id=candidate_id,
        cluster_key=cluster_key,
        profile_version="cr-score-v0.1",
        policy_version="cr-decision-v0.1",
        level=decision_level,
        total_score=total_score,
        push_eligible=decision_level in (DECISION_ALERT, DECISION_URGENT),
        suppress_labels=[],
        trigger_reasons=[],
        debug={},
    )
    return CRPresentedCandidate(
        candidate=cand,
        score_result=sr,
        decision=dec,
        candidate_id=candidate_id,
        cluster_key=cluster_key,
        display_title=display_title,
        representative_url=representative_url,
        decision_level=decision_level,
        total_score=total_score,
        trigger_reasons=[],
        suppress_labels=[],
    )


def _make_pipeline(
    *,
    run_label: str = "2026-06-10 09:00",
    cr_a_candidates: tuple[CRPresentedCandidate, ...] = (),
    cr_a_text: str = "CR-A body",
    high_score_suppressed_count: int = 0,
) -> CRPipelineResult:
    """Construct a CRPipelineResult directly with controlled CR-A fields.

    The dispatch planner only reads run_label, cr_a_candidates, cr_a_text, and
    high_score_suppressed_count; the remaining fields are filled with inert
    values so the frozen dataclass is well-formed.
    """
    return CRPipelineResult(
        run_label=run_label,
        primitives=(),
        candidates=(),
        score_results=(),
        decisions=(),
        presented_candidates=cr_a_candidates,
        cr_a_candidates=cr_a_candidates,
        cr_a_text=cr_a_text,
        markdown_audit_text="",
        html_audit_text="",
        high_score_suppressed_count=high_score_suppressed_count,
    )


# ---------------------------------------------------------------------------
# Test Group A — Model Shape
# ---------------------------------------------------------------------------


class TestModelShape(unittest.TestCase):
    def test_message_is_frozen(self):
        msg = CRDispatchMessage(
            text="x",
            format="plain_text",
            candidate_count=1,
            run_label="r",
            urgent_count=0,
            high_score_suppressed_count=0,
        )
        with self.assertRaises(dataclasses.FrozenInstanceError):
            msg.text = "y"  # type: ignore[misc]

    def test_plan_is_frozen(self):
        plan = build_cr_a_dispatch_plan(_make_pipeline())
        with self.assertRaises(dataclasses.FrozenInstanceError):
            plan.should_dispatch = False  # type: ignore[misc]

    def test_messages_is_tuple_when_ready(self):
        plan = build_cr_a_dispatch_plan(
            _make_pipeline(cr_a_candidates=(_make_presented(),))
        )
        self.assertIsInstance(plan.messages, tuple)

    def test_messages_is_tuple_when_blocked(self):
        plan = build_cr_a_dispatch_plan(_make_pipeline(cr_a_candidates=()))
        self.assertIsInstance(plan.messages, tuple)
        self.assertEqual(plan.messages, ())

    def test_format_is_plain_text(self):
        plan = build_cr_a_dispatch_plan(
            _make_pipeline(cr_a_candidates=(_make_presented(),))
        )
        self.assertEqual(plan.messages[0].format, "plain_text")


# ---------------------------------------------------------------------------
# Test Group B — Ready Plan
# ---------------------------------------------------------------------------


class TestReadyPlan(unittest.TestCase):
    def _pipeline(self) -> CRPipelineResult:
        return _make_pipeline(
            run_label="run-ready",
            cr_a_candidates=(
                _make_presented(candidate_id="c1", decision_level=DECISION_URGENT, total_score=90.0),
                _make_presented(candidate_id="c2", decision_level=DECISION_ALERT, total_score=70.0),
            ),
            cr_a_text="Two urgent/alert items.",
            high_score_suppressed_count=4,
        )

    def test_should_dispatch_true(self):
        plan = build_cr_a_dispatch_plan(self._pipeline())
        self.assertTrue(plan.should_dispatch)

    def test_reason_ready(self):
        plan = build_cr_a_dispatch_plan(self._pipeline())
        self.assertEqual(plan.reason, "ready")

    def test_one_message(self):
        plan = build_cr_a_dispatch_plan(self._pipeline())
        self.assertEqual(len(plan.messages), 1)

    def test_message_mirrors_pipeline(self):
        pipeline = self._pipeline()
        plan = build_cr_a_dispatch_plan(pipeline)
        msg = plan.messages[0]
        self.assertEqual(msg.text, pipeline.cr_a_text)
        self.assertEqual(msg.run_label, pipeline.run_label)
        self.assertEqual(msg.candidate_count, len(pipeline.cr_a_candidates))
        self.assertEqual(
            msg.high_score_suppressed_count,
            pipeline.high_score_suppressed_count,
        )

    def test_urgent_count_from_decision_levels(self):
        pipeline = self._pipeline()
        plan = build_cr_a_dispatch_plan(pipeline)
        # One urgent + one alert candidate → urgent_count == 1.
        self.assertEqual(plan.messages[0].urgent_count, 1)
        self.assertEqual(plan.urgent_count, 1)

    def test_plan_counts_mirror_message(self):
        pipeline = self._pipeline()
        plan = build_cr_a_dispatch_plan(pipeline)
        msg = plan.messages[0]
        self.assertEqual(plan.candidate_count, msg.candidate_count)
        self.assertEqual(plan.urgent_count, msg.urgent_count)
        self.assertEqual(
            plan.high_score_suppressed_count, msg.high_score_suppressed_count
        )
        self.assertEqual(plan.run_label, msg.run_label)

    def test_pipeline_not_mutated(self):
        pipeline = self._pipeline()
        before = (
            pipeline.cr_a_text,
            pipeline.run_label,
            pipeline.cr_a_candidates,
            pipeline.high_score_suppressed_count,
        )
        build_cr_a_dispatch_plan(pipeline)
        after = (
            pipeline.cr_a_text,
            pipeline.run_label,
            pipeline.cr_a_candidates,
            pipeline.high_score_suppressed_count,
        )
        self.assertEqual(before, after)


# ---------------------------------------------------------------------------
# Test Group C — No Selected Candidates
# ---------------------------------------------------------------------------


class TestNoSelectedCandidates(unittest.TestCase):
    def test_empty_pipeline_blocks(self):
        plan = build_cr_a_dispatch_plan(_make_pipeline(cr_a_candidates=()))
        self.assertFalse(plan.should_dispatch)
        self.assertEqual(plan.messages, ())
        self.assertEqual(plan.reason, "no_selected_candidates")
        self.assertEqual(plan.candidate_count, 0)

    def test_real_empty_pipeline_end_to_end(self):
        # Build a real (empty) pipeline through the actual pipeline assembly.
        pipeline = build_cr_pipeline_from_primitives([], run_label="empty")
        plan = build_cr_a_dispatch_plan(pipeline)
        self.assertFalse(plan.should_dispatch)
        self.assertEqual(plan.reason, "no_selected_candidates")
        self.assertEqual(plan.messages, ())
        self.assertEqual(plan.candidate_count, 0)


# ---------------------------------------------------------------------------
# Test Group D — Empty Text Guard
# ---------------------------------------------------------------------------


class TestEmptyTextGuard(unittest.TestCase):
    def _pipeline(self) -> CRPipelineResult:
        return _make_pipeline(
            cr_a_candidates=(_make_presented(),),
            cr_a_text="   \n  ",  # blank / whitespace only
        )

    def test_blank_text_blocks_by_default(self):
        plan = build_cr_a_dispatch_plan(self._pipeline(), allow_empty_text=False)
        self.assertFalse(plan.should_dispatch)
        self.assertEqual(plan.reason, "empty_text")
        self.assertEqual(plan.messages, ())

    def test_blank_text_allowed_when_opted_in(self):
        plan = build_cr_a_dispatch_plan(self._pipeline(), allow_empty_text=True)
        self.assertTrue(plan.should_dispatch)
        self.assertEqual(plan.reason, "ready")
        self.assertEqual(len(plan.messages), 1)

    def test_empty_string_text_blocks(self):
        pipeline = _make_pipeline(
            cr_a_candidates=(_make_presented(),), cr_a_text=""
        )
        plan = build_cr_a_dispatch_plan(pipeline)
        self.assertFalse(plan.should_dispatch)
        self.assertEqual(plan.reason, "empty_text")

    def test_candidate_check_precedes_text_check(self):
        # No candidates AND blank text → no_selected_candidates wins (order).
        pipeline = _make_pipeline(cr_a_candidates=(), cr_a_text="")
        plan = build_cr_a_dispatch_plan(pipeline)
        self.assertEqual(plan.reason, "no_selected_candidates")


# ---------------------------------------------------------------------------
# Test Group E — Threshold Behavior
# ---------------------------------------------------------------------------


class TestThresholdBehavior(unittest.TestCase):
    def test_min_one_allows_single_candidate(self):
        pipeline = _make_pipeline(
            cr_a_candidates=(_make_presented(),), cr_a_text="body"
        )
        plan = build_cr_a_dispatch_plan(pipeline, min_candidate_count=1)
        self.assertTrue(plan.should_dispatch)
        self.assertEqual(plan.reason, "ready")

    def test_min_two_blocks_single_candidate(self):
        pipeline = _make_pipeline(
            cr_a_candidates=(_make_presented(),), cr_a_text="body"
        )
        plan = build_cr_a_dispatch_plan(pipeline, min_candidate_count=2)
        self.assertFalse(plan.should_dispatch)
        self.assertEqual(plan.reason, "no_selected_candidates")
        self.assertEqual(plan.candidate_count, 1)

    def test_min_two_allows_two_candidates(self):
        pipeline = _make_pipeline(
            cr_a_candidates=(
                _make_presented(candidate_id="c1"),
                _make_presented(candidate_id="c2"),
            ),
            cr_a_text="body",
        )
        plan = build_cr_a_dispatch_plan(pipeline, min_candidate_count=2)
        self.assertTrue(plan.should_dispatch)


# ---------------------------------------------------------------------------
# Test Group F — Boundary
# ---------------------------------------------------------------------------


class TestSourceBoundary(unittest.TestCase):
    """dispatch_plan.py must not reference forbidden subsystems / tokens."""

    FORBIDDEN = (
        "trendradar.notification",
        "trendradar.storage",
        "trendradar.config",
        "trendradar.ai",
        "AIAnalysisResult",
        "telegram",
        "chat_id",
        "bot_token",
        "sender",
        "dispatcher",
        "cooldown",
        "dedupe",
        "alert_state",
    )

    def test_no_forbidden_tokens(self):
        import trendradar.cr.dispatch_plan as mod

        source = Path(mod.__file__).read_text(encoding="utf-8")
        for token in self.FORBIDDEN:
            self.assertNotIn(
                token, source, f"forbidden token {token!r} present in module"
            )


if __name__ == "__main__":
    unittest.main()
