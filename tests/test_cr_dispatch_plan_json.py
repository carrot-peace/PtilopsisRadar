# coding=utf-8
"""
PR-CR-A2: CR dispatch plan JSON serialization + artifact writing tests.

Covers:
  - Serialization: schema_version, dispatch_mode, should_dispatch, decision,
    reason, candidate_counts, selected candidate fields, missing_fields,
    candidate_summary, message_preview
  - Artifact writing: latest + archive dispatch_plan.json, JSON validity,
    parity between latest and archive, existing MD/HTML artifacts still work
  - Mode behavior: artifact/shadow/live write plan JSON, off does not write
  - Boundary: no Telegram, no notification, no receipt persistence, no cooldown

Pure tests only — no network, no Telegram, no real output directories.
"""

import ast
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

# Ensure project root is on path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from trendradar.cr.decision import (
    CRDecision,
    DECISION_ALERT,
    DECISION_SUPPRESS,
    DECISION_URGENT,
    DECISION_WATCH,
)
from trendradar.cr.dispatch_plan import (
    CRDispatchPlan,
    DECISION_DISPATCH,
    DECISION_NO_CANDIDATE,
    DECISION_SUPPRESSED,
    DECISION_UNKNOWN,
    DISPATCH_PLAN_SCHEMA_VERSION,
    build_cr_a_dispatch_plan,
    count_by_level,
    cr_dispatch_plan_to_json_dict,
)
from tests.cr_main_ast import load_cr_dispatch_hook
from trendradar.cr.event_identity import stable_event_key_for_candidate
from trendradar.cr.models import CRCandidate
from trendradar.cr.pipeline import CRPipelineResult, build_cr_pipeline_from_primitives
from trendradar.cr.presentation import CRPresentedCandidate
from trendradar.cr.runtime_dry_run import (
    CRRuntimeDryRunResult,
    build_and_write_cr_runtime_dry_run,
)
from trendradar.cr.artifacts import CRArtifactConfig, resolve_cr_artifact_paths
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
    push_eligible: bool | None = None,
    trigger_reasons: list[str] | None = None,
    suppress_labels: list[str] | None = None,
) -> CRPresentedCandidate:
    if trigger_reasons is None:
        trigger_reasons = []
    if suppress_labels is None:
        suppress_labels = []
    if push_eligible is None:
        push_eligible = decision_level in (DECISION_ALERT, DECISION_URGENT)
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
        trigger_reasons=list(trigger_reasons),
        debug={},
    )
    dec = CRDecision(
        candidate_id=candidate_id,
        cluster_key=cluster_key,
        profile_version="cr-score-v0.1",
        policy_version="cr-decision-v0.1",
        level=decision_level,
        total_score=total_score,
        push_eligible=push_eligible,
        suppress_labels=list(suppress_labels),
        trigger_reasons=list(trigger_reasons),
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
        trigger_reasons=list(trigger_reasons),
        suppress_labels=list(suppress_labels),
    )


def _make_pipeline(
    *,
    run_label: str = "2026-06-10 09:00",
    cr_a_candidates: tuple[CRPresentedCandidate, ...] = (),
    cr_a_text: str = "CR-A body",
    high_score_suppressed_count: int = 0,
    presented_candidates: tuple[CRPresentedCandidate, ...] | None = None,
) -> CRPipelineResult:
    if presented_candidates is None:
        presented_candidates = cr_a_candidates
    return CRPipelineResult(
        run_label=run_label,
        primitives=(),
        candidates=(),
        score_results=(),
        decisions=(),
        presented_candidates=presented_candidates,
        cr_a_candidates=cr_a_candidates,
        cr_a_text=cr_a_text,
        markdown_audit_text="",
        html_audit_text="",
        high_score_suppressed_count=high_score_suppressed_count,
    )


def _make_hotlist_item(title="Test Title", ranks=None):
    if ranks is None:
        ranks = [5]
    return {
        "title": title,
        "source_name": "weibo",
        "source_id": "weibo",
        "ranks": ranks,
        "count": 3,
        "first_time": "09:30",
        "last_time": "12:00",
        "url": "https://example.com",
        "mobileUrl": "",
        "is_new": False,
        "rank_timeline": [],
    }


def _hotlist_stats():
    return [
        {
            "word": "AI",
            "titles": [
                _make_hotlist_item(title="AI Title One", ranks=[3]),
            ],
            "count": 1,
            "position": 0,
        },
    ]


# ---------------------------------------------------------------------------
# Test Group A — Serialization: schema_version
# ---------------------------------------------------------------------------


class TestSchemaVersion(unittest.TestCase):
    def test_schema_version_present(self):
        plan = build_cr_a_dispatch_plan(_make_pipeline())
        d = cr_dispatch_plan_to_json_dict(plan, dispatch_mode="artifact")
        self.assertEqual(d["schema_version"], DISPATCH_PLAN_SCHEMA_VERSION)

    def test_schema_version_is_string(self):
        plan = build_cr_a_dispatch_plan(_make_pipeline())
        d = cr_dispatch_plan_to_json_dict(plan, dispatch_mode="artifact")
        self.assertIsInstance(d["schema_version"], str)


# ---------------------------------------------------------------------------
# Test Group B — Serialization: dispatch_mode
# ---------------------------------------------------------------------------


class TestDispatchMode(unittest.TestCase):
    def test_dispatch_mode_artifact(self):
        plan = build_cr_a_dispatch_plan(_make_pipeline())
        d = cr_dispatch_plan_to_json_dict(plan, dispatch_mode="artifact")
        self.assertEqual(d["dispatch_mode"], "artifact")

    def test_dispatch_mode_shadow(self):
        plan = build_cr_a_dispatch_plan(_make_pipeline())
        d = cr_dispatch_plan_to_json_dict(plan, dispatch_mode="shadow")
        self.assertEqual(d["dispatch_mode"], "shadow")

    def test_dispatch_mode_live(self):
        plan = build_cr_a_dispatch_plan(_make_pipeline())
        d = cr_dispatch_plan_to_json_dict(plan, dispatch_mode="live")
        self.assertEqual(d["dispatch_mode"], "live")


# ---------------------------------------------------------------------------
# Test Group C — Serialization: should_dispatch + decision/reason
# ---------------------------------------------------------------------------


class TestDecisionSemantics(unittest.TestCase):
    def test_no_candidate_decision(self):
        plan = build_cr_a_dispatch_plan(_make_pipeline(cr_a_candidates=()))
        d = cr_dispatch_plan_to_json_dict(plan, dispatch_mode="artifact")
        self.assertFalse(d["should_dispatch"])
        self.assertEqual(d["decision"], DECISION_NO_CANDIDATE)
        self.assertEqual(d["reason"], "no_selected_candidates")

    def test_dispatch_decision(self):
        presented = (_make_presented(),)
        pipeline = _make_pipeline(
            cr_a_candidates=presented,
            presented_candidates=presented,
            cr_a_text="body",
        )
        plan = build_cr_a_dispatch_plan(pipeline)
        d = cr_dispatch_plan_to_json_dict(
            plan, dispatch_mode="artifact", presented_candidates=presented
        )
        self.assertTrue(d["should_dispatch"])
        self.assertEqual(d["decision"], DECISION_DISPATCH)
        self.assertEqual(d["reason"], "ready")

    def test_suppress_decision_empty_text(self):
        presented = (_make_presented(),)
        pipeline = _make_pipeline(
            cr_a_candidates=presented,
            presented_candidates=presented,
            cr_a_text="   ",
        )
        plan = build_cr_a_dispatch_plan(pipeline)
        d = cr_dispatch_plan_to_json_dict(
            plan, dispatch_mode="artifact", presented_candidates=presented
        )
        self.assertFalse(d["should_dispatch"])
        self.assertEqual(d["decision"], DECISION_SUPPRESSED)
        self.assertEqual(d["reason"], "empty_text")

    def test_unknown_decision_for_unmapped_reason(self):
        plan = CRDispatchPlan(
            should_dispatch=False,
            messages=(),
            reason="some_future_reason",
            run_label="r",
            candidate_count=0,
            urgent_count=0,
            high_score_suppressed_count=0,
        )
        d = cr_dispatch_plan_to_json_dict(plan, dispatch_mode="artifact")
        self.assertEqual(d["decision"], DECISION_UNKNOWN)


# ---------------------------------------------------------------------------
# Test Group D — Serialization: candidate_counts
# ---------------------------------------------------------------------------


class TestCandidateCounts(unittest.TestCase):
    def test_empty_candidates(self):
        plan = build_cr_a_dispatch_plan(_make_pipeline())
        d = cr_dispatch_plan_to_json_dict(plan, dispatch_mode="artifact")
        self.assertEqual(
            d["candidate_counts"],
            {"urgent": 0, "alert": 0, "watch": 0, "suppress": 0, "push_eligible": 0},
        )

    def test_mixed_level_counts(self):
        presented = (
            _make_presented(candidate_id="c1", decision_level=DECISION_URGENT, total_score=90.0),
            _make_presented(candidate_id="c2", decision_level=DECISION_ALERT, total_score=70.0),
            _make_presented(candidate_id="c3", decision_level=DECISION_WATCH, total_score=40.0),
            _make_presented(
                candidate_id="c4",
                decision_level=DECISION_SUPPRESS,
                total_score=50.0,
                push_eligible=False,
            ),
        )
        plan = build_cr_a_dispatch_plan(_make_pipeline(cr_a_candidates=presented[:2], presented_candidates=presented, cr_a_text="body"))
        d = cr_dispatch_plan_to_json_dict(
            plan, dispatch_mode="artifact", presented_candidates=presented
        )
        self.assertEqual(d["candidate_counts"]["urgent"], 1)
        self.assertEqual(d["candidate_counts"]["alert"], 1)
        self.assertEqual(d["candidate_counts"]["watch"], 1)
        self.assertEqual(d["candidate_counts"]["suppress"], 1)
        self.assertEqual(d["candidate_counts"]["push_eligible"], 2)

    def test_count_by_level_helper(self):
        presented = (
            _make_presented(candidate_id="c1", decision_level=DECISION_URGENT),
            _make_presented(candidate_id="c2", decision_level=DECISION_URGENT),
            _make_presented(candidate_id="c3", decision_level=DECISION_ALERT),
        )
        counts = count_by_level(presented)
        self.assertEqual(counts[DECISION_URGENT], 2)
        self.assertEqual(counts[DECISION_ALERT], 1)
        self.assertEqual(counts[DECISION_WATCH], 0)
        self.assertEqual(counts[DECISION_SUPPRESS], 0)


# ---------------------------------------------------------------------------
# Test Group E — Serialization: selected candidate fields
# ---------------------------------------------------------------------------


class TestSelectedCandidate(unittest.TestCase):
    def test_selected_event_key_uses_stable_event_identity(self):
        presented = (
            _make_presented(
                candidate_id="c1",
                cluster_key="ev1",
                display_title="Urgent Topic",
                decision_level=DECISION_URGENT,
                total_score=90.0,
            ),
        )
        pipeline = _make_pipeline(
            cr_a_candidates=presented,
            presented_candidates=presented,
            cr_a_text="body",
        )
        plan = build_cr_a_dispatch_plan(pipeline)
        d = cr_dispatch_plan_to_json_dict(
            plan,
            dispatch_mode="artifact",
            presented_candidates=presented,
            cr_a_candidates=presented,
        )
        self.assertEqual(d["selected_event_key"], stable_event_key_for_candidate(presented[0]))

    def test_selected_event_key_ignores_cluster_key_url_and_candidate_id_changes(self):
        base = _make_presented(
            candidate_id="c-base",
            cluster_key="cluster-a",
            display_title="Event Title",
            representative_url="https://example.com/article-a",
            decision_level=DECISION_URGENT,
            total_score=90.0,
        )
        cluster_only = _make_presented(
            candidate_id="c-base",
            cluster_key="cluster-b",
            display_title="Event Title",
            representative_url="https://example.com/article-a",
            decision_level=DECISION_URGENT,
            total_score=90.0,
        )
        candidate_id_only = _make_presented(
            candidate_id="c-variant",
            cluster_key="cluster-a",
            display_title="Event Title",
            representative_url="https://example.com/article-a",
            decision_level=DECISION_URGENT,
            total_score=90.0,
        )
        url_only = _make_presented(
            candidate_id="c-base",
            cluster_key="cluster-a",
            display_title="Event Title",
            representative_url="https://example.com/article-b",
            decision_level=DECISION_URGENT,
            total_score=90.0,
        )
        variants = {
            "base": base,
            "cluster_key": cluster_only,
            "candidate_id": candidate_id_only,
            "representative_url": url_only,
        }
        selected_event_keys = []

        for variant_name, pc in variants.items():
            with self.subTest(variant=variant_name):
                pipeline = _make_pipeline(
                    cr_a_candidates=(pc,),
                    presented_candidates=(pc,),
                    cr_a_text="body",
                )
                plan = build_cr_a_dispatch_plan(pipeline)
                d = cr_dispatch_plan_to_json_dict(
                    plan,
                    dispatch_mode="artifact",
                    presented_candidates=(pc,),
                    cr_a_candidates=(pc,),
                )

                selected_event_key = d["selected_event_key"]
                self.assertTrue(plan.should_dispatch)
                self.assertEqual(d["selected_candidate_id"], pc.candidate_id)
                self.assertIsNotNone(selected_event_key)
                self.assertTrue(selected_event_key.startswith("cr-event-v1:"))
                self.assertNotEqual(selected_event_key, pc.candidate_id)
                self.assertNotEqual(selected_event_key, pc.cluster_key)
                selected_event_keys.append(selected_event_key)

        self.assertEqual(
            len(set(selected_event_keys)),
            1,
            f"selected_event_key differs across variants: {selected_event_keys}",
        )

    def test_selected_fields_when_dispatching(self):
        presented = (
            _make_presented(
                candidate_id="c1",
                cluster_key="ev1",
                display_title="Urgent Topic",
                decision_level=DECISION_URGENT,
                total_score=90.0,
            ),
        )
        pipeline = _make_pipeline(
            cr_a_candidates=presented,
            presented_candidates=presented,
            cr_a_text="body",
        )
        plan = build_cr_a_dispatch_plan(pipeline)
        d = cr_dispatch_plan_to_json_dict(
            plan,
            dispatch_mode="artifact",
            presented_candidates=presented,
            cr_a_candidates=presented,
        )
        self.assertEqual(
            d["selected_event_key"],
            stable_event_key_for_candidate(presented[0]),
        )
        self.assertEqual(d["selected_candidate_id"], "c1")
        self.assertEqual(d["selected_title"], "Urgent Topic")
        self.assertEqual(d["selected_level"], DECISION_URGENT)
        self.assertEqual(d["selected_score"], 90.0)

    def test_selected_fields_none_when_not_dispatching(self):
        plan = build_cr_a_dispatch_plan(_make_pipeline(cr_a_candidates=()))
        d = cr_dispatch_plan_to_json_dict(plan, dispatch_mode="artifact")
        self.assertIsNone(d["selected_event_key"])
        self.assertIsNone(d["selected_candidate_id"])
        self.assertIsNone(d["selected_title"])
        self.assertIsNone(d["selected_level"])
        self.assertIsNone(d["selected_score"])

    def test_selected_from_cr_a_candidates_not_presented(self):
        """selected_* must come from cr_a_candidates, not presented_candidates.

        When presented_candidates contains a lower-ranked candidate before the
        CR-A selected one, the JSON must still report the CR-A candidate.
        """
        alert_low = _make_presented(
            candidate_id="c-low",
            cluster_key="ev-low",
            display_title="Low Alert",
            decision_level=DECISION_ALERT,
            total_score=60.0,
        )
        urgent_high = _make_presented(
            candidate_id="c-high",
            cluster_key="ev-high",
            display_title="High Urgent",
            decision_level=DECISION_URGENT,
            total_score=95.0,
        )
        presented = (alert_low, urgent_high)
        cr_a = (urgent_high,)
        pipeline = _make_pipeline(
            cr_a_candidates=cr_a,
            presented_candidates=presented,
            cr_a_text="body",
        )
        plan = build_cr_a_dispatch_plan(pipeline)
        d = cr_dispatch_plan_to_json_dict(
            plan,
            dispatch_mode="artifact",
            presented_candidates=presented,
            cr_a_candidates=cr_a,
        )
        self.assertEqual(d["selected_candidate_id"], "c-high")
        self.assertEqual(d["selected_level"], DECISION_URGENT)
        self.assertEqual(d["selected_title"], "High Urgent")
        self.assertEqual(d["selected_score"], 95.0)


# ---------------------------------------------------------------------------
# Test Group F — Serialization: missing_fields
# ---------------------------------------------------------------------------


class TestMissingFields(unittest.TestCase):
    def test_no_missing_when_dispatching(self):
        presented = (
            _make_presented(
                cluster_key="ev1",
                decision_level=DECISION_URGENT,
                total_score=90.0,
            ),
        )
        pipeline = _make_pipeline(
            cr_a_candidates=presented,
            presented_candidates=presented,
            cr_a_text="body",
        )
        plan = build_cr_a_dispatch_plan(pipeline)
        d = cr_dispatch_plan_to_json_dict(
            plan, dispatch_mode="artifact", presented_candidates=presented
        )
        self.assertEqual(d["missing_fields"], [])

    def test_missing_fields_empty_when_not_dispatching(self):
        plan = build_cr_a_dispatch_plan(_make_pipeline(cr_a_candidates=()))
        d = cr_dispatch_plan_to_json_dict(plan, dispatch_mode="artifact")
        self.assertEqual(d["missing_fields"], [])

    def test_suppression_only_dispatch_needs_no_selected_event(self):
        pipeline = _make_pipeline(
            cr_a_candidates=(),
            cr_a_text="Suppressed (high-score): 1",
            high_score_suppressed_count=1,
        )
        plan = build_cr_a_dispatch_plan(pipeline)

        data = cr_dispatch_plan_to_json_dict(
            plan, dispatch_mode="live"
        )

        self.assertTrue(data["should_dispatch"])
        self.assertEqual(data["reason"], "ready_suppressed_only")
        self.assertIsNone(data["selected_event_key"])
        self.assertIsNone(data["selected_candidate_id"])
        self.assertEqual(data["missing_fields"], [])


# ---------------------------------------------------------------------------
# Test Group G — Serialization: candidate_summary
# ---------------------------------------------------------------------------


class TestCandidateSummary(unittest.TestCase):
    def test_summary_empty_when_no_presented_candidates(self):
        plan = build_cr_a_dispatch_plan(_make_pipeline())
        d = cr_dispatch_plan_to_json_dict(plan, dispatch_mode="artifact")
        self.assertEqual(d["candidate_summary"], [])

    def test_summary_populated_with_presented_candidates(self):
        presented = (
            _make_presented(
                candidate_id="c1",
                cluster_key="ev1",
                display_title="Topic A",
                decision_level=DECISION_ALERT,
                total_score=70.0,
                trigger_reasons=["cross_evidence"],
            ),
            _make_presented(
                candidate_id="c2",
                cluster_key="ev2",
                display_title="Topic B",
                decision_level=DECISION_WATCH,
                total_score=40.0,
            ),
        )
        plan = build_cr_a_dispatch_plan(_make_pipeline(cr_a_candidates=presented[:1], cr_a_text="body"))
        d = cr_dispatch_plan_to_json_dict(
            plan, dispatch_mode="artifact", presented_candidates=presented
        )
        self.assertEqual(len(d["candidate_summary"]), 2)
        first = d["candidate_summary"][0]
        self.assertEqual(first["cluster_key"], "ev1")
        self.assertEqual(first["candidate_id"], "c1")
        self.assertEqual(first["title"], "Topic A")
        self.assertEqual(first["level"], DECISION_ALERT)
        self.assertEqual(first["score"], 70.0)
        self.assertTrue(first["push_eligible"])
        self.assertEqual(first["trigger_reasons"], ["cross_evidence"])

    def test_summary_fields_use_null_for_unavailable(self):
        """source_count and platform_count are 0 when source_items is empty."""
        presented = (_make_presented(),)
        plan = build_cr_a_dispatch_plan(_make_pipeline(cr_a_candidates=presented, cr_a_text="body"))
        d = cr_dispatch_plan_to_json_dict(
            plan, dispatch_mode="artifact", presented_candidates=presented
        )
        first = d["candidate_summary"][0]
        self.assertEqual(first["source_count"], 0)
        self.assertEqual(first["platform_count"], 0)
        self.assertEqual(first["suppress_reasons"], [])


# ---------------------------------------------------------------------------
# Test Group H — Serialization: message_preview
# ---------------------------------------------------------------------------


class TestMessagePreview(unittest.TestCase):
    def test_message_preview_when_dispatching(self):
        presented = (_make_presented(),)
        pipeline = _make_pipeline(
            cr_a_candidates=presented,
            presented_candidates=presented,
            cr_a_text="Alert body text",
        )
        plan = build_cr_a_dispatch_plan(pipeline)
        d = cr_dispatch_plan_to_json_dict(
            plan, dispatch_mode="artifact", presented_candidates=presented
        )
        self.assertEqual(d["message_preview"], "Alert body text")

    def test_message_preview_none_when_not_dispatching(self):
        plan = build_cr_a_dispatch_plan(_make_pipeline(cr_a_candidates=()))
        d = cr_dispatch_plan_to_json_dict(plan, dispatch_mode="artifact")
        self.assertIsNone(d["message_preview"])


# ---------------------------------------------------------------------------
# Test Group I — Serialization: run_id + created_at
# ---------------------------------------------------------------------------


class TestRunMetadata(unittest.TestCase):
    def test_run_id_matches_run_label(self):
        plan = build_cr_a_dispatch_plan(
            _make_pipeline(run_label="run-20260617-090000")
        )
        d = cr_dispatch_plan_to_json_dict(plan, dispatch_mode="artifact")
        self.assertEqual(d["run_id"], "run-20260617-090000")

    def test_created_at_none_by_default(self):
        plan = build_cr_a_dispatch_plan(_make_pipeline())
        d = cr_dispatch_plan_to_json_dict(plan, dispatch_mode="artifact")
        self.assertIsNone(d["created_at"])

    def test_created_at_from_parameter(self):
        plan = build_cr_a_dispatch_plan(_make_pipeline())
        d = cr_dispatch_plan_to_json_dict(
            plan, dispatch_mode="artifact", created_at="2026-06-17T09:00:00+08:00"
        )
        self.assertEqual(d["created_at"], "2026-06-17T09:00:00+08:00")


# ---------------------------------------------------------------------------
# Test Group J — Serialization: JSON round-trip
# ---------------------------------------------------------------------------


class TestJsonRoundTrip(unittest.TestCase):
    def test_dict_is_json_serializable(self):
        presented = (
            _make_presented(
                candidate_id="c1",
                cluster_key="ev1",
                decision_level=DECISION_URGENT,
                total_score=90.0,
            ),
        )
        pipeline = _make_pipeline(
            cr_a_candidates=presented,
            presented_candidates=presented,
            cr_a_text="body",
        )
        plan = build_cr_a_dispatch_plan(pipeline)
        d = cr_dispatch_plan_to_json_dict(
            plan,
            dispatch_mode="live",
            presented_candidates=presented,
            created_at="2026-06-17T09:00:00",
        )
        # Must not raise.
        serialized = json.dumps(d, ensure_ascii=False)
        parsed = json.loads(serialized)
        self.assertEqual(parsed["schema_version"], DISPATCH_PLAN_SCHEMA_VERSION)
        self.assertEqual(parsed["dispatch_mode"], "live")
        self.assertTrue(parsed["should_dispatch"])


# ---------------------------------------------------------------------------
# Test Group K — Artifact Writing
# ---------------------------------------------------------------------------


class TestArtifactWriting(unittest.TestCase):
    def _run(self, tmp, *, hotlist=None, dispatch_mode="artifact"):
        return build_and_write_cr_runtime_dry_run(
            hotlist_stats=hotlist or _hotlist_stats(),
            run_label="run-k",
            artifact_config=CRArtifactConfig(root_dir=Path(tmp)),
            dispatch_mode=dispatch_mode,
        )

    def test_writes_dispatch_plan_json_latest(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = self._run(tmp)
            self.assertTrue(
                result.dispatch_plan_json_paths.dispatch_plan_latest_path.exists()
            )

    def test_writes_dispatch_plan_json_archive(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = self._run(tmp)
            self.assertTrue(
                result.dispatch_plan_json_paths.dispatch_plan_archive_path.exists()
            )

    def test_dispatch_plan_json_is_valid_json(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = self._run(tmp)
            path = result.dispatch_plan_json_paths.dispatch_plan_latest_path
            data = json.loads(path.read_text(encoding="utf-8"))
            self.assertIsInstance(data, dict)

    def test_dispatch_plan_json_has_schema_version(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = self._run(tmp)
            path = result.dispatch_plan_json_paths.dispatch_plan_latest_path
            data = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(data["schema_version"], DISPATCH_PLAN_SCHEMA_VERSION)

    def test_latest_and_archive_contain_same_data(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = self._run(tmp)
            latest = json.loads(
                result.dispatch_plan_json_paths.dispatch_plan_latest_path.read_text(
                    encoding="utf-8"
                )
            )
            archive = json.loads(
                result.dispatch_plan_json_paths.dispatch_plan_archive_path.read_text(
                    encoding="utf-8"
                )
            )
            self.assertEqual(latest, archive)

    def test_existing_markdown_still_written(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = self._run(tmp)
            self.assertTrue(result.artifact_paths.markdown_archive_path.exists())
            self.assertTrue(result.artifact_paths.latest_markdown_path.exists())

    def test_existing_html_still_written(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = self._run(tmp)
            self.assertTrue(result.artifact_paths.html_archive_path.exists())
            self.assertTrue(result.artifact_paths.latest_html_path.exists())

    def test_dispatch_plan_json_paths_populated_on_result(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = self._run(tmp)
            self.assertIsInstance(
                result.dispatch_plan_json_paths.dispatch_plan_latest_path, Path
            )
            self.assertIsInstance(
                result.dispatch_plan_json_paths.dispatch_plan_archive_path, Path
            )


# ---------------------------------------------------------------------------
# Test Group L — Mode Behavior
# ---------------------------------------------------------------------------


class TestModeBehavior(unittest.TestCase):
    def test_artifact_mode_writes_plan_json(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = build_and_write_cr_runtime_dry_run(
                hotlist_stats=_hotlist_stats(),
                run_label="mode-test",
                artifact_config=CRArtifactConfig(root_dir=Path(tmp)),
                dispatch_mode="artifact",
            )
            path = result.dispatch_plan_json_paths.dispatch_plan_latest_path
            self.assertTrue(path.exists())
            data = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(data["dispatch_mode"], "artifact")

    def test_shadow_mode_writes_plan_json(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = build_and_write_cr_runtime_dry_run(
                hotlist_stats=_hotlist_stats(),
                run_label="mode-test",
                artifact_config=CRArtifactConfig(root_dir=Path(tmp)),
                dispatch_mode="shadow",
            )
            path = result.dispatch_plan_json_paths.dispatch_plan_latest_path
            self.assertTrue(path.exists())
            data = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(data["dispatch_mode"], "shadow")

    def test_live_mode_without_gate_writes_plan_json(self):
        """live mode without a dispatch sink still writes plan JSON."""
        with tempfile.TemporaryDirectory() as tmp:
            result = build_and_write_cr_runtime_dry_run(
                hotlist_stats=_hotlist_stats(),
                run_label="mode-test",
                artifact_config=CRArtifactConfig(root_dir=Path(tmp)),
                dispatch_mode="live",
                dispatch_sink=None,
            )
            path = result.dispatch_plan_json_paths.dispatch_plan_latest_path
            self.assertTrue(path.exists())
            data = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(data["dispatch_mode"], "live")
            # No sink means no execution.
            self.assertIsNone(result.dispatch_execution)

    def test_off_mode_not_called(self):
        """When mode is off, build_and_write_cr_runtime_dry_run is never
        called from __main__.py — verified by AST structure, not by
        invoking with off mode (the function always writes plan JSON).
        """
        hook = load_cr_dispatch_hook()
        self.assertIn(hook.runtime_call, list(ast.walk(hook.off_gate)))

    def test_dispatch_mode_defaults_to_artifact_when_none(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = build_and_write_cr_runtime_dry_run(
                hotlist_stats=_hotlist_stats(),
                run_label="mode-test",
                artifact_config=CRArtifactConfig(root_dir=Path(tmp)),
                dispatch_mode=None,
            )
            path = result.dispatch_plan_json_paths.dispatch_plan_latest_path
            data = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(data["dispatch_mode"], "artifact")


# ---------------------------------------------------------------------------
# Test Group M — Artifact Config / Paths
# ---------------------------------------------------------------------------


class TestArtifactConfigPaths(unittest.TestCase):
    def test_dispatch_plan_archive_dirname_default(self):
        config = CRArtifactConfig()
        self.assertEqual(config.dispatch_plan_archive_dirname, "archive/dispatch_plan")

    def test_dispatch_plan_filename_default(self):
        config = CRArtifactConfig()
        self.assertEqual(config.dispatch_plan_filename, "dispatch_plan.json")

    def test_resolve_paths_includes_dispatch_plan(self):
        config = CRArtifactConfig(root_dir=Path("/tmp/test-cr"))
        paths = resolve_cr_artifact_paths(run_label="run-1", config=config)
        self.assertIn("dispatch_plan", str(paths.dispatch_plan_archive_path))
        self.assertIn("dispatch_plan.json", str(paths.dispatch_plan_latest_path))

    def test_dispatch_plan_archive_uses_safe_label(self):
        config = CRArtifactConfig(root_dir=Path("/tmp/test-cr"))
        paths = resolve_cr_artifact_paths(
            run_label="2026-06-17 09:00:00", config=config
        )
        self.assertIn(
            "2026-06-17-09-00-00", str(paths.dispatch_plan_archive_path)
        )


# ---------------------------------------------------------------------------
# Test Group N — End-to-end with real pipeline
# ---------------------------------------------------------------------------


class TestEndToEnd(unittest.TestCase):
    def test_empty_pipeline_writes_valid_plan_json(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = build_and_write_cr_runtime_dry_run(
                run_label="e2e-empty",
                artifact_config=CRArtifactConfig(root_dir=Path(tmp)),
                dispatch_mode="artifact",
            )
            path = result.dispatch_plan_json_paths.dispatch_plan_latest_path
            data = json.loads(path.read_text(encoding="utf-8"))
            self.assertFalse(data["should_dispatch"])
            self.assertEqual(data["decision"], "no_candidate")
            self.assertEqual(data["candidate_counts"]["urgent"], 0)

    def test_hotlist_input_writes_plan_json_with_candidates(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = build_and_write_cr_runtime_dry_run(
                hotlist_stats=_hotlist_stats(),
                run_label="e2e-hotlist",
                artifact_config=CRArtifactConfig(root_dir=Path(tmp)),
                dispatch_mode="shadow",
            )
            path = result.dispatch_plan_json_paths.dispatch_plan_latest_path
            data = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(data["schema_version"], DISPATCH_PLAN_SCHEMA_VERSION)
            self.assertEqual(data["dispatch_mode"], "shadow")
            self.assertEqual(data["run_id"], "e2e-hotlist")
            self.assertIsInstance(data["candidate_summary"], list)
            self.assertIsInstance(data["candidate_counts"], dict)


# ---------------------------------------------------------------------------
# Test Group O — Boundary
# ---------------------------------------------------------------------------


class TestSourceBoundary(unittest.TestCase):
    """dispatch_plan.py serialization must not reference forbidden subsystems."""

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
        "dedupe",
        "alert_state",
    )

    def test_no_forbidden_tokens_in_dispatch_plan(self):
        import trendradar.cr.dispatch_plan as mod

        source = Path(mod.__file__).read_text(encoding="utf-8")
        for token in self.FORBIDDEN:
            self.assertNotIn(
                token, source, f"forbidden token {token!r} present in module"
            )


if __name__ == "__main__":
    unittest.main()
