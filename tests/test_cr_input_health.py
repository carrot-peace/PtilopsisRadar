# coding=utf-8
"""CR input-health policy and fail-closed runtime tests."""

import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import Mock, patch

from trendradar.cr.artifacts import CRArtifactConfig
from trendradar.cr.decision import (
    CRDecision,
    CRDecisionPolicy,
    DECISION_SUPPRESS,
)
from trendradar.cr.dispatch_executor import CRMemoryDispatchSink
from trendradar.cr.input_health import (
    CRInputHealthPolicy,
    REASON_HOTLIST_SUCCESS_RATIO_LOW,
    REASON_RSS_ALL_FAILED,
    REASON_STALE_INPUT,
    STATUS_DEGRADED,
    STATUS_FAIL_CLOSED,
    collection_coverage_summary,
    evaluate_cr_input_health,
    input_health_to_json_dict,
    input_item_identity,
    policy_from_env,
)
from trendradar.cr.models import CRCandidate, CRRunContext, CRSourceItem
from trendradar.cr.pipeline import CRPipelineConfig, CRPipelineResult
from trendradar.cr.presentation import (
    CRPresentationRun,
    CRPresentedCandidate,
    render_cr_a_text,
)
from trendradar.cr.runtime_dry_run import build_and_write_cr_runtime_dry_run
from trendradar.cr.scoring import CRScoreResult

NOW = datetime(2026, 7, 11, 12, 0, tzinfo=timezone.utc)


def _item(title: str, source_id: str) -> dict:
    return {
        "title": title,
        "source_name": source_id,
        "source_id": source_id,
        "ranks": [1],
        "count": 10,
        "first_time": "09:30",
        "last_time": "12:00",
        "url": f"https://example.com/{source_id}",
        "mobileUrl": "",
        "is_new": False,
        "rank_timeline": [],
    }


def _stats(*items: dict) -> list[dict]:
    return [
        {"word": f"topic-{index}", "titles": [item], "count": 1, "position": index}
        for index, item in enumerate(items)
    ]


def _health(
    *, configured=("a",), successful=("a",), failed=(), observed=(),
    generated_at: datetime = NOW, rss_configured=(), rss_successful=(),
    rss_failed=(),
):
    return evaluate_cr_input_health(
        hotlist_configured_ids=configured,
        hotlist_successful_ids=successful,
        hotlist_failed_ids=failed,
        rss_configured_ids=rss_configured,
        rss_successful_ids=rss_successful,
        rss_failed_ids=rss_failed,
        observed_item_identities=observed,
        snapshot_generated_at=generated_at.isoformat(),
        now=NOW,
    )


def _suppression_pipeline(*, fresh: bool) -> CRPipelineResult:
    candidate = CRCandidate(
        candidate_id="suppressed-1",
        cluster_key="suppressed-topic",
        display_title="Suppressed Topic",
        source_items=[
            CRSourceItem(
                source_type="hotlist",
                source_id="a",
                title="Suppressed Topic",
                observed_in_current_run=fresh,
            )
        ],
    )
    score = CRScoreResult(
        candidate_id=candidate.candidate_id,
        cluster_key=candidate.cluster_key,
        profile_version="test-score",
        total_score=90.0,
    )
    decision = CRDecision(
        candidate_id=candidate.candidate_id,
        cluster_key=candidate.cluster_key,
        profile_version="test-score",
        policy_version="test-decision",
        level=DECISION_SUPPRESS,
        total_score=90.0,
        push_eligible=False,
        suppress_labels=["test_suppress"],
    )
    presented = CRPresentedCandidate(
        candidate=candidate,
        score_result=score,
        decision=decision,
        candidate_id=candidate.candidate_id,
        cluster_key=candidate.cluster_key,
        display_title=candidate.display_title,
        representative_url=None,
        decision_level=DECISION_SUPPRESS,
        total_score=90.0,
        suppress_labels=["test_suppress"],
    )
    run = CRPresentationRun(
        run_label="health-run",
        candidates=[],
        high_score_suppressed_count=1,
    )
    return CRPipelineResult(
        run_label="health-run",
        primitives=(),
        candidates=(candidate,),
        score_results=(score,),
        decisions=(decision,),
        presented_candidates=(presented,),
        cr_a_candidates=(),
        cr_a_text=render_cr_a_text(run),
        markdown_audit_text="audit",
        html_audit_text="<p>audit</p>",
        high_score_suppressed_count=1,
    )


class TestPolicy(unittest.TestCase):
    def test_defaults(self) -> None:
        policy, warnings = policy_from_env({})
        self.assertEqual(policy.stale_after_minutes, 120)
        self.assertEqual(policy.degraded_success_ratio, 0.67)
        self.assertEqual(warnings, ())

    def test_invalid_values_fall_back_with_auditable_warnings(self) -> None:
        policy, warnings = policy_from_env({
            "PTILOPSIS_CR_INPUT_STALE_AFTER_MINUTES": "nan",
            "PTILOPSIS_CR_INPUT_DEGRADED_SUCCESS_RATIO": "2",
        })
        self.assertEqual(policy, CRInputHealthPolicy())
        self.assertEqual(len(warnings), 2)
        self.assertTrue(all(value.startswith("invalid_env:") for value in warnings))

    def test_stale_boundary_is_strictly_greater(self) -> None:
        at_boundary = _health(generated_at=NOW - timedelta(minutes=120))
        stale = _health(generated_at=NOW - timedelta(minutes=121))
        self.assertNotIn(REASON_STALE_INPUT, at_boundary.reasons)
        self.assertEqual(stale.status, STATUS_FAIL_CLOSED)
        self.assertIn(REASON_STALE_INPUT, stale.reasons)

    def test_degraded_source_rules(self) -> None:
        health = _health(
            configured=("a", "b", "c"), successful=("a",), failed=("b", "c"),
            rss_configured=("r1",), rss_failed=("r1",),
        )
        self.assertEqual(health.status, STATUS_DEGRADED)
        self.assertIn(REASON_HOTLIST_SUCCESS_RATIO_LOW, health.reasons)
        self.assertIn(REASON_RSS_ALL_FAILED, health.reasons)

    def test_collection_coverage_summary(self) -> None:
        health = _health(
            configured=("a", "b", "c"),
            successful=("a", "b"),
            failed=("c",),
            rss_configured=("r1",),
            rss_failed=("r1",),
        )
        summary = collection_coverage_summary(health)
        self.assertEqual(summary["configured"], 4)
        self.assertEqual(summary["successful"], 2)
        self.assertEqual(summary["failed"], 2)
        self.assertEqual(summary["ratio"], 0.5)
        self.assertIn("2/4", summary["warning"])

    def test_recovery_markers_are_serialized_for_audit(self) -> None:
        health = evaluate_cr_input_health(
            hotlist_successful_ids=("a",),
            hotlist_recovered_ids=("a",),
            rss_successful_ids=("r1",),
            rss_recovered_ids=("r1",),
            recovery_state_status="tracked",
        )
        payload = input_health_to_json_dict(health)
        self.assertEqual(payload["hotlist"]["recovered_ids"], ["a"])
        self.assertEqual(payload["rss"]["recovered_ids"], ["r1"])
        self.assertEqual(payload["recovery"]["state_status"], "tracked")
        self.assertTrue(payload["recovery"]["new_burst_evidence_trusted"])

    def test_failed_source_wins_over_overlapping_success(self) -> None:
        health = evaluate_cr_input_health(
            hotlist_configured_ids=("a",),
            hotlist_successful_ids=("a",),
            hotlist_failed_ids=("a",),
        )
        self.assertEqual(health.hotlist.successful_ids, ())
        self.assertEqual(health.hotlist.failed_ids, ("a",))
        self.assertTrue(health.fail_closed)
        summary = collection_coverage_summary(health)
        self.assertEqual(summary["successful"], 0)
        self.assertEqual(summary["failed"], 1)


class TestMainWiring(unittest.TestCase):
    def test_main_preserves_rss_failed_ids_and_builds_health_context(self) -> None:
        main_source = (
            Path(__file__).resolve().parents[1] / "trendradar" / "__main__.py"
        ).read_text(encoding="utf-8")
        service_source = (
            Path(__file__).resolve().parents[1]
            / "trendradar"
            / "application"
            / "services"
            / "cr_notification.py"
        ).read_text(encoding="utf-8")
        self.assertIn("self._cr_rss_failed_ids", main_source)
        self.assertIn("rss_data.failed_ids", main_source)
        self.assertIn("evaluate_cr_input_health", service_source)
        self.assertIn("observed_item_identities=frozenset", main_source)
        self.assertIn("load_cr_input_health_state", service_source)
        self.assertIn("recovered_source_ids", service_source)
        self.assertIn("save_cr_input_health_state", service_source)


class TestRuntimeGate(unittest.TestCase):
    def _run(self, tmp: str, *, stats: list[dict], health, mode="live", sink=None):
        return build_and_write_cr_runtime_dry_run(
            hotlist_stats=stats,
            run_label="health-run",
            run_context=CRRunContext(
                mode="current",
                observed_item_identities=health.observed_item_identities,
                input_health=health,
            ),
            pipeline_config=CRPipelineConfig(
                decision=CRDecisionPolicy(alert_threshold=1.0),
            ),
            artifact_config=CRArtifactConfig(root_dir=Path(tmp)),
            dispatch_mode=mode,
            dispatch_sink=sink,
            dispatch_state_path=Path(tmp) / "state.json",
            deferred_queue_path=Path(tmp) / "queue.json",
            now=NOW,
        )

    def test_all_hotlist_failed_blocks_without_side_effects(self) -> None:
        sink = CRMemoryDispatchSink()
        health = _health(configured=("a",), successful=(), failed=("a",))
        with tempfile.TemporaryDirectory() as tmp:
            result = self._run(tmp, stats=_stats(_item("historical", "a")), health=health, sink=sink)
            self.assertEqual(result.dispatch_plan.reason, "insufficient_fresh_sources")
            self.assertEqual(sink.submitted_messages, [])
            self.assertIsNone(result.dispatch_state_save)
            self.assertIsNone(result.deferred_queue_load)
            self.assertFalse((Path(tmp) / "state.json").exists())
            self.assertFalse((Path(tmp) / "queue.json").exists())

    def test_stale_snapshot_receipt_and_audits_are_consistent(self) -> None:
        observed = {input_item_identity(source_type="hotlist", source_id="a", title="fresh")}
        health = _health(observed=observed, generated_at=NOW - timedelta(minutes=121))
        with tempfile.TemporaryDirectory() as tmp:
            result = self._run(tmp, stats=_stats(_item("fresh", "a")), health=health)
            self.assertEqual(result.dispatch_plan.reason, "stale_input")
            plan = json.loads(result.dispatch_plan_json_paths.dispatch_plan_latest_path.read_text())
            receipt = json.loads(result.dispatch_receipt_json_paths.dispatch_receipt_latest_path.read_text())
            self.assertEqual(plan["input_health"]["status"], STATUS_FAIL_CLOSED)
            self.assertEqual(receipt["input_health"], plan["input_health"])
            self.assertEqual(receipt["receipts"][0]["status"], "skipped_stale_input")
            self.assertIn("## Input Health", result.pipeline.markdown_audit_text)
            self.assertIn("Input Health", result.pipeline.html_audit_text)

    def test_degraded_mixed_input_sends_only_fresh_candidate(self) -> None:
        fresh = _item("fresh candidate", "a")
        stale = _item("stale candidate", "b")
        observed = {input_item_identity(source_type="hotlist", source_id="a", title=fresh["title"])}
        health = _health(
            configured=("a", "b", "c"), successful=("a",), failed=("b", "c"),
            observed=observed,
        )
        sink = CRMemoryDispatchSink()
        with tempfile.TemporaryDirectory() as tmp:
            result = self._run(tmp, stats=_stats(stale, fresh), health=health, sink=sink)
            self.assertTrue(result.dispatch_plan.should_dispatch)
            self.assertEqual(result.dispatch_plan.candidate_count, 1)
            self.assertEqual(len(sink.submitted_messages), 1)
            text = sink.submitted_messages[0].text
            self.assertIn("fresh candidate", text)
            self.assertNotIn("stale candidate", text)

    def test_degraded_fresh_suppression_only_is_dispatched(self) -> None:
        health = _health(
            configured=("a", "b", "c"),
            successful=("a",),
            failed=("b", "c"),
        )
        sink = CRMemoryDispatchSink()
        pipeline = _suppression_pipeline(fresh=True)
        with tempfile.TemporaryDirectory() as tmp, patch.dict(
            build_and_write_cr_runtime_dry_run.__globals__,
            {
                "build_cr_pipeline_from_primitives": Mock(
                    return_value=pipeline
                )
            },
        ):
            result = self._run(
                tmp, stats=[], health=health, sink=sink
            )

        self.assertEqual(health.status, STATUS_DEGRADED)
        self.assertEqual(
            result.dispatch_plan.reason, "ready_suppressed_only"
        )
        self.assertEqual(
            result.dispatch_plan.high_score_suppressed_count, 1
        )
        self.assertEqual(len(sink.submitted_messages), 1)

    def test_degraded_stale_suppression_only_is_blocked(self) -> None:
        health = _health(
            configured=("a", "b", "c"),
            successful=("a",),
            failed=("b", "c"),
        )
        sink = CRMemoryDispatchSink()
        pipeline = _suppression_pipeline(fresh=False)
        with tempfile.TemporaryDirectory() as tmp, patch.dict(
            build_and_write_cr_runtime_dry_run.__globals__,
            {
                "build_cr_pipeline_from_primitives": Mock(
                    return_value=pipeline
                )
            },
        ):
            result = self._run(
                tmp, stats=[], health=health, sink=sink
            )

        self.assertEqual(
            result.dispatch_plan.reason, "insufficient_fresh_sources"
        )
        self.assertEqual(
            result.dispatch_plan.high_score_suppressed_count, 0
        )
        self.assertEqual(sink.submitted_messages, [])

    def test_rss_all_failed_does_not_block_fresh_hotlist(self) -> None:
        fresh = _item("fresh hotlist", "a")
        observed = {input_item_identity(source_type="hotlist", source_id="a", title=fresh["title"])}
        health = _health(
            observed=observed,
            rss_configured=("r1",), rss_failed=("r1",),
        )
        sink = CRMemoryDispatchSink()
        with tempfile.TemporaryDirectory() as tmp:
            result = self._run(tmp, stats=_stats(fresh), health=health, sink=sink)
            self.assertEqual(health.status, STATUS_DEGRADED)
            self.assertTrue(result.dispatch_plan.should_dispatch)
            self.assertEqual(len(sink.submitted_messages), 1)
            self.assertIn(
                "Collection coverage: 1/2 (1 failed)",
                sink.submitted_messages[0].text,
            )

    def test_one_fresh_item_allows_mixed_candidate(self) -> None:
        fresh = _item("shared event", "a")
        stale = _item("shared event", "b")
        observed = {input_item_identity(source_type="hotlist", source_id="a", title="shared event")}
        health = _health(
            configured=("a", "b"), successful=("a", "b"), observed=observed,
        )
        sink = CRMemoryDispatchSink()
        with tempfile.TemporaryDirectory() as tmp:
            result = self._run(tmp, stats=_stats(fresh, stale), health=health, sink=sink)
            self.assertTrue(result.dispatch_plan.should_dispatch)
            self.assertEqual(len(sink.submitted_messages), 1)

    def test_healthy_but_stale_only_candidate_is_blocked(self) -> None:
        observed = {input_item_identity(source_type="hotlist", source_id="a", title="other")}
        health = _health(observed=observed)
        sink = CRMemoryDispatchSink()
        with tempfile.TemporaryDirectory() as tmp:
            result = self._run(
                tmp, stats=_stats(_item("stale only", "a")), health=health, sink=sink,
            )
            self.assertEqual(result.dispatch_plan.reason, "insufficient_fresh_sources")
            self.assertEqual(sink.submitted_messages, [])

    def test_artifact_mode_preserves_gate_receipt_status(self) -> None:
        health = _health(configured=("a",), successful=(), failed=("a",))
        with tempfile.TemporaryDirectory() as tmp:
            result = self._run(
                tmp, stats=_stats(_item("historical", "a")), health=health,
                mode="artifact",
            )
            receipt = json.loads(result.dispatch_receipt_json_paths.dispatch_receipt_latest_path.read_text())
            self.assertEqual(
                receipt["receipts"][0]["status"],
                "skipped_insufficient_fresh_sources",
            )


class TestAuditNonePlaceholder(unittest.TestCase):
    """Snapshot fields rendered as 'unknown' rather than literal None."""

    def _run(self, tmp: str, health):
        return build_and_write_cr_runtime_dry_run(
            hotlist_stats=_stats(_item("x", "a")),
            run_label="audit-run",
            run_context=CRRunContext(
                mode="current",
                observed_item_identities=health.observed_item_identities,
                input_health=health,
            ),
            pipeline_config=CRPipelineConfig(
                decision=CRDecisionPolicy(alert_threshold=1.0),
            ),
            artifact_config=CRArtifactConfig(root_dir=Path(tmp)),
            dispatch_mode="artifact",
            dispatch_state_path=Path(tmp) / "state.json",
            deferred_queue_path=Path(tmp) / "queue.json",
            now=NOW,
        )

    def test_snapshot_none_fields_show_unknown_in_markdown(self) -> None:
        health = evaluate_cr_input_health(
            hotlist_configured_ids=("a",),
            hotlist_failed_ids=("a",),
            now=NOW,
        )
        self.assertIsNone(health.snapshot_generated_at)
        self.assertIsNone(health.snapshot_age_minutes)
        with tempfile.TemporaryDirectory() as tmp:
            result = self._run(tmp, health)
            md = result.pipeline.markdown_audit_text
            self.assertIn("unknown", md)
            self.assertNotIn("`None`", md)

    def test_snapshot_none_fields_show_unknown_in_html(self) -> None:
        health = evaluate_cr_input_health(
            hotlist_configured_ids=("a",),
            hotlist_failed_ids=("a",),
            now=NOW,
        )
        with tempfile.TemporaryDirectory() as tmp:
            result = self._run(tmp, health)
            html = result.pipeline.html_audit_text
            self.assertIn("unknown", html)
            self.assertNotIn("None", html)

    def test_age_zero_is_not_replaced(self) -> None:
        health = evaluate_cr_input_health(
            hotlist_configured_ids=("a",),
            hotlist_successful_ids=("a",),
            snapshot_generated_at=NOW.isoformat(),
            now=NOW,
        )
        self.assertEqual(health.snapshot_age_minutes, 0.0)
        with tempfile.TemporaryDirectory() as tmp:
            result = self._run(tmp, health)
            md = result.pipeline.markdown_audit_text
            self.assertIn("0.0", md)


if __name__ == "__main__":
    unittest.main()
