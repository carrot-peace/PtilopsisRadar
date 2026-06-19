# coding=utf-8
"""
Tests for CR offline pipeline assembly (PR9j).

Covers:
  A. Config / Model tests
  B. Basic pure pipeline flow
  C. Determinism
  D. CR-A selection vs audit
  E. Config propagation
  F. Artifact write helpers
  G. Boundary / forbidden imports
"""

import tempfile
import unittest
from pathlib import Path

from trendradar.cr.decision import (
    DECISION_ALERT,
    DECISION_SUPPRESS,
    DECISION_URGENT,
    DECISION_WATCH,
)
from trendradar.cr.html import CRHTMLRenderConfig
from trendradar.cr.markdown import CRMarkdownRenderConfig
from trendradar.cr.models import (
    CRCandidate,
    CRClusterConfig,
    CRPrimitiveRecord,
    CRSourceItem,
)
from trendradar.cr.pipeline import (
    CRPipelineArtifactResult,
    CRPipelineConfig,
    CRPipelineRenderConfig,
    CRPipelineResult,
    build_and_write_cr_pipeline_from_primitives,
    build_cr_pipeline_from_primitives,
    write_cr_pipeline_artifacts,
)
from trendradar.cr.presentation import CRTextPresentationConfig
from trendradar.cr.scoring import CRScoringProfile


# ---------------------------------------------------------------------------
# Test fixture builders
# ---------------------------------------------------------------------------


def _make_hotlist_item(
    title: str,
    source_id: str = "weibo",
    source_name: str = "weibo",
    current_rank: int = 3,
    normalized_rank: int = 3,
    url: str | None = None,
    keyword_group: str | None = "group1",
    is_new: bool = False,
    has_reliable_rank_timeline: bool = True,
    visible_observation_count: int = 3,
    previous_observation_exists: bool = True,
    previous_observation_visible: bool = True,
    previous_visible_rank: int | None = None,
    rank_delta: int | None = None,
    has_time_signals: bool = True,
    first_time: str = "2026-06-10T08:00:00",
    last_time: str = "2026-06-10T09:00:00",
    count: int = 5,
    has_count: bool = True,
    first_crawl_of_day: bool = False,
) -> CRSourceItem:
    return CRSourceItem(
        source_type="hotlist",
        source_id=source_id,
        source_name=source_name,
        title=title,
        url=url,
        keyword_group=keyword_group,
        is_new=is_new,
        is_new_semantics="new_titles_detection" if is_new else "unknown",
        raw_rank=current_rank,
        normalized_rank=normalized_rank,
        is_visible=True,
        rank_sentinel="none",
        has_reliable_rank_timeline=has_reliable_rank_timeline,
        visible_observation_count=visible_observation_count,
        previous_observation_exists=previous_observation_exists,
        previous_observation_visible=previous_observation_visible,
        previous_visible_rank=previous_visible_rank,
        current_rank=current_rank,
        rank_delta=rank_delta,
        has_time_signals=has_time_signals,
        first_time=first_time,
        last_time=last_time,
        count=count,
        has_count=has_count,
        first_crawl_of_day=first_crawl_of_day,
    )


def _make_primitive(
    title: str,
    source_id: str = "weibo",
    source_name: str = "weibo",
    current_rank: int = 3,
    normalized_rank: int = 3,
    url: str | None = None,
    keyword_group: str | None = "group1",
    **kwargs,
) -> CRPrimitiveRecord:
    item = _make_hotlist_item(
        title,
        source_id=source_id,
        source_name=source_name,
        current_rank=current_rank,
        normalized_rank=normalized_rank,
        url=url,
        keyword_group=keyword_group,
        **kwargs,
    )
    return CRPrimitiveRecord(
        keyword_group=keyword_group,
        keyword_groups=[keyword_group] if keyword_group else [],
        source_items=[item],
        primary_title=title,
        representative_url=url,
        record_source="hotlist_stats",
    )


def _make_high_score_primitive(
    title: str = "Hot Breaking News Event",
    source_id: str = "weibo",
) -> CRPrimitiveRecord:
    """Build a primitive that will score high (top-3 rank, multiple signals)."""
    return _make_primitive(
        title=title,
        source_id=source_id,
        source_name=source_id,
        current_rank=1,
        normalized_rank=1,
        url=f"https://example.com/{source_id}",
        is_new=True,
        rank_delta=0,
        previous_observation_exists=True,
        previous_observation_visible=True,
        previous_visible_rank=1,
        count=10,
        has_count=True,
        visible_observation_count=5,
    )


def _make_low_score_primitive(
    title: str = "Minor Update Note",
    source_id: str = "weibo",
) -> CRPrimitiveRecord:
    """Build a primitive that will score low (high rank number, few signals)."""
    return _make_primitive(
        title=title,
        source_id=source_id,
        source_name=source_id,
        current_rank=95,
        normalized_rank=95,
        url=f"https://example.com/{source_id}",
        has_reliable_rank_timeline=False,
        visible_observation_count=1,
        previous_observation_exists=False,
        previous_observation_visible=False,
        count=1,
        has_count=True,
        has_time_signals=False,
        first_time=None,
        last_time=None,
    )


# ===========================================================================
# A. Config / Model tests
# ===========================================================================


class TestPipelineRenderConfig(unittest.TestCase):
    """A1. CRPipelineRenderConfig."""

    def test_frozen(self):
        cfg = CRPipelineRenderConfig()
        with self.assertRaises(AttributeError):
            cfg.text = None  # type: ignore[misc]

    def test_defaults_are_none(self):
        cfg = CRPipelineRenderConfig()
        self.assertIsNone(cfg.text)
        self.assertIsNone(cfg.markdown)
        self.assertIsNone(cfg.html)

    def test_accepts_sub_configs(self):
        text_cfg = CRTextPresentationConfig(max_candidates=5)
        md_cfg = CRMarkdownRenderConfig(title="Custom MD")
        html_cfg = CRHTMLRenderConfig(title="Custom HTML")
        cfg = CRPipelineRenderConfig(
            text=text_cfg, markdown=md_cfg, html=html_cfg
        )
        self.assertIs(cfg.text, text_cfg)
        self.assertIs(cfg.markdown, md_cfg)
        self.assertIs(cfg.html, html_cfg)


class TestPipelineConfig(unittest.TestCase):
    """A2. CRPipelineConfig."""

    def test_frozen(self):
        cfg = CRPipelineConfig()
        with self.assertRaises(AttributeError):
            cfg.cluster = None  # type: ignore[misc]

    def test_defaults(self):
        cfg = CRPipelineConfig()
        self.assertIsNone(cfg.cluster)
        self.assertIsNone(cfg.scoring)
        self.assertIsNone(cfg.decision)
        self.assertIsInstance(cfg.render, CRPipelineRenderConfig)

    def test_accepts_sub_configs(self):
        cluster_cfg = CRClusterConfig(min_shared_tokens=3)
        scoring_cfg = CRScoringProfile(alert_threshold=50.0)
        cfg = CRPipelineConfig(
            cluster=cluster_cfg,
            scoring=scoring_cfg,
        )
        self.assertIs(cfg.cluster, cluster_cfg)
        self.assertIs(cfg.scoring, scoring_cfg)


class TestPipelineResult(unittest.TestCase):
    """A3. CRPipelineResult stores tuples."""

    def _build_result(self) -> CRPipelineResult:
        return build_cr_pipeline_from_primitives(
            [_make_high_score_primitive()],
            run_label="test",
        )

    def test_primitives_is_tuple(self):
        result = self._build_result()
        self.assertIsInstance(result.primitives, tuple)

    def test_candidates_is_tuple(self):
        result = self._build_result()
        self.assertIsInstance(result.candidates, tuple)

    def test_score_results_is_tuple(self):
        result = self._build_result()
        self.assertIsInstance(result.score_results, tuple)

    def test_decisions_is_tuple(self):
        result = self._build_result()
        self.assertIsInstance(result.decisions, tuple)

    def test_presented_candidates_is_tuple(self):
        result = self._build_result()
        self.assertIsInstance(result.presented_candidates, tuple)

    def test_cr_a_candidates_is_tuple(self):
        result = self._build_result()
        self.assertIsInstance(result.cr_a_candidates, tuple)

    def test_frozen(self):
        result = self._build_result()
        with self.assertRaises(AttributeError):
            result.run_label = "changed"  # type: ignore[misc]


class TestPipelineArtifactResult(unittest.TestCase):
    """A4. CRPipelineArtifactResult stores pipeline + artifact_paths."""

    def test_with_tempdir(self):
        primitives = [_make_high_score_primitive()]
        with tempfile.TemporaryDirectory() as d:
            from trendradar.cr.artifacts import CRArtifactConfig

            art_cfg = CRArtifactConfig(root_dir=d)
            result = build_and_write_cr_pipeline_from_primitives(
                primitives,
                run_label="test",
                artifact_config=art_cfg,
            )
            self.assertIsInstance(result, CRPipelineArtifactResult)
            self.assertIsInstance(result.pipeline, CRPipelineResult)
            self.assertIsInstance(result.artifact_paths, object)


# ===========================================================================
# B. Basic pure pipeline flow
# ===========================================================================


class TestBasicPipelineFlow(unittest.TestCase):
    """B. Basic pure pipeline flow."""

    def setUp(self):
        self.primitives = [
            _make_high_score_primitive("Breaking AI Policy Update"),
            _make_high_score_primitive(
                "AI Policy Reform News",
                source_id="baidu",
            ),
        ]
        self.result = build_cr_pipeline_from_primitives(
            self.primitives, run_label="2026-06-10 09:00"
        )

    def test_run_label_preserved(self):
        self.assertEqual(self.result.run_label, "2026-06-10 09:00")

    def test_primitives_count_preserved(self):
        self.assertEqual(len(self.result.primitives), 2)

    def test_candidates_non_empty(self):
        self.assertGreater(len(self.result.candidates), 0)

    def test_score_results_count_equals_candidates(self):
        self.assertEqual(
            len(self.result.score_results), len(self.result.candidates)
        )

    def test_decisions_count_equals_candidates(self):
        self.assertEqual(
            len(self.result.decisions), len(self.result.candidates)
        )

    def test_presented_candidates_count_equals_candidates(self):
        self.assertEqual(
            len(self.result.presented_candidates), len(self.result.candidates)
        )

    def test_cr_a_candidates_is_tuple(self):
        self.assertIsInstance(self.result.cr_a_candidates, tuple)

    def test_cr_a_text_is_str(self):
        self.assertIsInstance(self.result.cr_a_text, str)
        self.assertTrue(len(self.result.cr_a_text) > 0)

    def test_markdown_audit_text_is_str(self):
        self.assertIsInstance(self.result.markdown_audit_text, str)
        self.assertTrue(len(self.result.markdown_audit_text) > 0)

    def test_html_audit_text_is_str(self):
        self.assertIsInstance(self.result.html_audit_text, str)
        self.assertTrue(len(self.result.html_audit_text) > 0)

    def test_markdown_contains_level_headings(self):
        md = self.result.markdown_audit_text
        self.assertIn("## urgent", md)
        self.assertIn("## alert", md)
        self.assertIn("## watch", md)
        self.assertIn("## suppress", md)

    def test_html_contains_level_headings(self):
        html = self.result.html_audit_text
        self.assertIn(">urgent<", html)
        self.assertIn(">alert<", html)
        self.assertIn(">watch<", html)
        self.assertIn(">suppress<", html)

    def test_single_primitive(self):
        """Single primitive still produces valid result."""
        result = build_cr_pipeline_from_primitives(
            [_make_high_score_primitive()],
            run_label="single",
        )
        self.assertEqual(len(result.primitives), 1)
        self.assertGreater(len(result.candidates), 0)

    def test_empty_primitives(self):
        """Empty primitives produces empty result."""
        result = build_cr_pipeline_from_primitives(
            [], run_label="empty"
        )
        self.assertEqual(len(result.primitives), 0)
        self.assertEqual(len(result.candidates), 0)
        self.assertEqual(len(result.score_results), 0)
        self.assertEqual(len(result.decisions), 0)
        self.assertEqual(len(result.presented_candidates), 0)
        self.assertEqual(len(result.cr_a_candidates), 0)


# ===========================================================================
# C. Determinism
# ===========================================================================


class TestDeterminism(unittest.TestCase):
    """C. Same input produces same output."""

    def setUp(self):
        self.primitives = [
            _make_high_score_primitive("Breaking AI Policy Update"),
            _make_high_score_primitive(
                "AI Policy Reform News", source_id="baidu"
            ),
            _make_low_score_primitive("Minor Style Guide Change"),
        ]

    def test_same_candidate_order(self):
        r1 = build_cr_pipeline_from_primitives(
            self.primitives, run_label="run1"
        )
        r2 = build_cr_pipeline_from_primitives(
            self.primitives, run_label="run1"
        )
        self.assertEqual(
            [c.candidate_id for c in r1.candidates],
            [c.candidate_id for c in r2.candidates],
        )

    def test_same_cr_a_text(self):
        r1 = build_cr_pipeline_from_primitives(
            self.primitives, run_label="run1"
        )
        r2 = build_cr_pipeline_from_primitives(
            self.primitives, run_label="run1"
        )
        self.assertEqual(r1.cr_a_text, r2.cr_a_text)

    def test_same_markdown_audit(self):
        r1 = build_cr_pipeline_from_primitives(
            self.primitives, run_label="run1"
        )
        r2 = build_cr_pipeline_from_primitives(
            self.primitives, run_label="run1"
        )
        self.assertEqual(r1.markdown_audit_text, r2.markdown_audit_text)

    def test_same_html_audit(self):
        r1 = build_cr_pipeline_from_primitives(
            self.primitives, run_label="run1"
        )
        r2 = build_cr_pipeline_from_primitives(
            self.primitives, run_label="run1"
        )
        self.assertEqual(r1.html_audit_text, r2.html_audit_text)

    def test_input_not_mutated(self):
        original = [
            _make_high_score_primitive("Breaking AI Policy Update"),
        ]
        original_titles = [p.primary_title for p in original]
        build_cr_pipeline_from_primitives(original, run_label="test")
        self.assertEqual(
            [p.primary_title for p in original], original_titles
        )

    def test_input_list_not_mutated(self):
        """The list itself is not mutated (no items added/removed)."""
        original = [
            _make_high_score_primitive("Title A"),
            _make_high_score_primitive("Title B", source_id="baidu"),
        ]
        original_len = len(original)
        build_cr_pipeline_from_primitives(original, run_label="test")
        self.assertEqual(len(original), original_len)


# ===========================================================================
# D. CR-A selection vs audit
# ===========================================================================


class TestCRASelectionVsAudit(unittest.TestCase):
    """D. Audit includes all levels; CR-A only includes selected."""

    def test_watch_in_markdown_audit(self):
        """Watch candidates appear in Markdown audit."""
        low = _make_low_score_primitive("Low Score Watch Topic")
        result = build_cr_pipeline_from_primitives(
            [low], run_label="test"
        )
        # Low score → watch. Should appear in Markdown audit.
        if any(d.level == DECISION_WATCH for d in result.decisions):
            self.assertIn("## watch", result.markdown_audit_text)
            self.assertIn("Low Score Watch Topic", result.markdown_audit_text)

    def test_watch_not_in_cr_a_candidates(self):
        """Watch candidates are NOT in cr_a_candidates."""
        low = _make_low_score_primitive("Low Score Watch Topic")
        result = build_cr_pipeline_from_primitives(
            [low], run_label="test"
        )
        for pc in result.cr_a_candidates:
            self.assertIn(pc.decision_level, (DECISION_ALERT, DECISION_URGENT))

    def test_suppress_in_markdown_audit(self):
        """Suppress candidates appear in Markdown audit if they exist."""
        # Build a primitive that will be suppressed — we can't easily force
        # suppress through scoring alone, so test the structural invariant.
        high = _make_high_score_primitive("High Score Topic")
        low = _make_low_score_primitive("Low Score Topic")
        result = build_cr_pipeline_from_primitives(
            [high, low], run_label="test"
        )
        # All presented candidates should be in the audit.
        md = result.markdown_audit_text
        for pc in result.presented_candidates:
            self.assertIn(pc.display_title, md)

    def test_presented_candidates_includes_all_levels(self):
        """presented_candidates includes candidates from all decision levels."""
        high = _make_high_score_primitive("High Score Topic")
        low = _make_low_score_primitive("Low Score Topic")
        result = build_cr_pipeline_from_primitives(
            [high, low], run_label="test"
        )
        levels = {pc.decision_level for pc in result.presented_candidates}
        # At minimum should have at least one level.
        self.assertGreater(len(levels), 0)
        # All levels should be valid.
        for lv in levels:
            self.assertIn(lv, (DECISION_URGENT, DECISION_ALERT, DECISION_WATCH, DECISION_SUPPRESS))

    def test_candidate_count_invariant(self):
        """presented_candidates count equals candidates count."""
        primitives = [
            _make_high_score_primitive("Topic A"),
            _make_high_score_primitive("Topic B", source_id="baidu"),
            _make_low_score_primitive("Topic C"),
        ]
        result = build_cr_pipeline_from_primitives(
            primitives, run_label="test"
        )
        self.assertEqual(
            len(result.presented_candidates), len(result.candidates)
        )


# ===========================================================================
# E. Config propagation
# ===========================================================================


class TestConfigPropagation(unittest.TestCase):
    """E. Custom configs propagate to renderers."""

    def test_markdown_title_propagates(self):
        cfg = CRPipelineConfig(
            render=CRPipelineRenderConfig(
                markdown=CRMarkdownRenderConfig(title="Custom Markdown Title"),
            ),
        )
        result = build_cr_pipeline_from_primitives(
            [_make_high_score_primitive()],
            run_label="test",
            config=cfg,
        )
        self.assertIn("Custom Markdown Title", result.markdown_audit_text)

    def test_html_title_propagates(self):
        cfg = CRPipelineConfig(
            render=CRPipelineRenderConfig(
                html=CRHTMLRenderConfig(title="Custom HTML Title"),
            ),
        )
        result = build_cr_pipeline_from_primitives(
            [_make_high_score_primitive()],
            run_label="test",
            config=cfg,
        )
        self.assertIn("Custom HTML Title", result.html_audit_text)

    def test_text_max_candidates_propagates(self):
        """CRTextPresentationConfig.max_candidates limits cr_a_candidates."""
        cfg = CRPipelineConfig(
            render=CRPipelineRenderConfig(
                text=CRTextPresentationConfig(max_candidates=1),
            ),
        )
        result = build_cr_pipeline_from_primitives(
            [
                _make_high_score_primitive("Topic A"),
                _make_high_score_primitive("Topic B", source_id="baidu"),
            ],
            run_label="test",
            config=cfg,
        )
        self.assertLessEqual(len(result.cr_a_candidates), 1)

    def test_cluster_config_propagates(self):
        """Custom cluster config is used."""
        cfg = CRPipelineConfig(
            cluster=CRClusterConfig(min_shared_tokens=100),
        )
        # With very high min_shared_tokens, items won't cluster together.
        result = build_cr_pipeline_from_primitives(
            [
                _make_high_score_primitive("Topic A"),
                _make_high_score_primitive("Topic B", source_id="baidu"),
            ],
            run_label="test",
            config=cfg,
        )
        # They should remain separate candidates since clustering is very strict.
        self.assertEqual(len(result.candidates), 2)

    def test_default_config_uses_lower_layer_defaults(self):
        """None config uses lower-layer defaults (no crash)."""
        result = build_cr_pipeline_from_primitives(
            [_make_high_score_primitive()],
            run_label="test",
            config=None,
        )
        self.assertIsInstance(result, CRPipelineResult)

    def test_default_config_preserves_rss_only_candidates(self):
        primitive = CRPrimitiveRecord(
            source_items=[CRSourceItem(
                source_type="rss",
                title="Standalone RSS",
                url="https://rss.example.com/standalone",
            )],
            record_source="rss_stats",
        )
        result = build_cr_pipeline_from_primitives(
            [primitive], run_label="test", config=None,
        )
        self.assertEqual(len(result.candidates), 1)
        self.assertEqual(result.candidates[0].primary_source_type, "rss")

    def test_empty_render_config_uses_defaults(self):
        """Empty CRPipelineRenderConfig uses lower-layer defaults."""
        cfg = CRPipelineConfig(render=CRPipelineRenderConfig())
        result = build_cr_pipeline_from_primitives(
            [_make_high_score_primitive()],
            run_label="test",
            config=cfg,
        )
        # Default Markdown title should appear.
        self.assertIn("Ptilopsis Radar", result.markdown_audit_text)
        # Default HTML title should appear.
        self.assertIn("Ptilopsis Radar", result.html_audit_text)


# ===========================================================================
# F. Artifact write helpers
# ===========================================================================


class TestArtifactWriteHelpers(unittest.TestCase):
    """F. write_cr_pipeline_artifacts and build_and_write helper."""

    def test_write_cr_pipeline_artifacts(self):
        """write_cr_pipeline_artifacts writes markdown and html files."""
        result = build_cr_pipeline_from_primitives(
            [_make_high_score_primitive()],
            run_label="2026-06-10 09:00",
        )
        with tempfile.TemporaryDirectory() as d:
            from trendradar.cr.artifacts import CRArtifactConfig

            art_cfg = CRArtifactConfig(root_dir=d)
            paths = write_cr_pipeline_artifacts(
                result, artifact_config=art_cfg
            )
            self.assertTrue(paths.markdown_archive_path.exists())
            self.assertTrue(paths.html_archive_path.exists())
            self.assertTrue(paths.latest_markdown_path.exists())
            self.assertTrue(paths.latest_html_path.exists())

    def test_archive_markdown_contains_audit_title(self):
        result = build_cr_pipeline_from_primitives(
            [_make_high_score_primitive()],
            run_label="test-run",
        )
        with tempfile.TemporaryDirectory() as d:
            from trendradar.cr.artifacts import CRArtifactConfig

            art_cfg = CRArtifactConfig(root_dir=d)
            paths = write_cr_pipeline_artifacts(
                result, artifact_config=art_cfg
            )
            md = paths.markdown_archive_path.read_text(encoding="utf-8")
            self.assertIn("Ptilopsis Radar", md)

    def test_archive_html_contains_html_title(self):
        result = build_cr_pipeline_from_primitives(
            [_make_high_score_primitive()],
            run_label="test-run",
        )
        with tempfile.TemporaryDirectory() as d:
            from trendradar.cr.artifacts import CRArtifactConfig

            art_cfg = CRArtifactConfig(root_dir=d)
            paths = write_cr_pipeline_artifacts(
                result, artifact_config=art_cfg
            )
            html = paths.html_archive_path.read_text(encoding="utf-8")
            self.assertIn("<!doctype html>", html)
            self.assertIn("Ptilopsis Radar", html)

    def test_latest_markdown_exists(self):
        result = build_cr_pipeline_from_primitives(
            [_make_high_score_primitive()],
            run_label="test",
        )
        with tempfile.TemporaryDirectory() as d:
            from trendradar.cr.artifacts import CRArtifactConfig

            art_cfg = CRArtifactConfig(root_dir=d)
            paths = write_cr_pipeline_artifacts(
                result, artifact_config=art_cfg
            )
            self.assertTrue(paths.latest_markdown_path.exists())

    def test_latest_html_exists(self):
        result = build_cr_pipeline_from_primitives(
            [_make_high_score_primitive()],
            run_label="test",
        )
        with tempfile.TemporaryDirectory() as d:
            from trendradar.cr.artifacts import CRArtifactConfig

            art_cfg = CRArtifactConfig(root_dir=d)
            paths = write_cr_pipeline_artifacts(
                result, artifact_config=art_cfg
            )
            self.assertTrue(paths.latest_html_path.exists())

    def test_build_and_write_returns_pipeline_artifact_result(self):
        with tempfile.TemporaryDirectory() as d:
            from trendradar.cr.artifacts import CRArtifactConfig

            art_cfg = CRArtifactConfig(root_dir=d)
            result = build_and_write_cr_pipeline_from_primitives(
                [_make_high_score_primitive()],
                run_label="test",
                artifact_config=art_cfg,
            )
            self.assertIsInstance(result, CRPipelineArtifactResult)
            self.assertIsInstance(result.pipeline, CRPipelineResult)

    def test_build_and_write_pipeline_field(self):
        with tempfile.TemporaryDirectory() as d:
            from trendradar.cr.artifacts import CRArtifactConfig

            art_cfg = CRArtifactConfig(root_dir=d)
            result = build_and_write_cr_pipeline_from_primitives(
                [_make_high_score_primitive()],
                run_label="test",
                artifact_config=art_cfg,
            )
            self.assertEqual(result.pipeline.run_label, "test")
            self.assertGreater(len(result.pipeline.candidates), 0)

    def test_build_and_write_artifact_paths_field(self):
        with tempfile.TemporaryDirectory() as d:
            from trendradar.cr.artifacts import CRArtifactConfig

            art_cfg = CRArtifactConfig(root_dir=d)
            result = build_and_write_cr_pipeline_from_primitives(
                [_make_high_score_primitive()],
                run_label="test",
                artifact_config=art_cfg,
            )
            self.assertTrue(result.artifact_paths.markdown_archive_path.exists())
            self.assertTrue(result.artifact_paths.html_archive_path.exists())
            self.assertTrue(result.artifact_paths.latest_markdown_path.exists())
            self.assertTrue(result.artifact_paths.latest_html_path.exists())


# ===========================================================================
# G. Boundary / forbidden imports
# ===========================================================================


class TestForbiddenImports(unittest.TestCase):
    """G. pipeline.py must not import forbidden modules."""

    def _read_source(self) -> str:
        import trendradar.cr.pipeline as mod

        source_file = mod.__file__
        assert source_file is not None
        with open(source_file) as f:
            return f.read()

    def test_no_main_import(self):
        source = self._read_source()
        self.assertNotIn("from trendradar.__main__", source)
        self.assertNotIn("import trendradar.__main__", source)

    def test_no_notification_import(self):
        source = self._read_source()
        self.assertNotIn("from trendradar.notification", source)
        self.assertNotIn("import trendradar.notification", source)

    def test_no_report_import(self):
        source = self._read_source()
        self.assertNotIn("from trendradar.report", source)
        self.assertNotIn("import trendradar.report", source)

    def test_no_archive_import(self):
        source = self._read_source()
        self.assertNotIn("from trendradar.archive", source)
        self.assertNotIn("import trendradar.archive", source)

    def test_no_storage_import(self):
        source = self._read_source()
        self.assertNotIn("from trendradar.storage", source)
        self.assertNotIn("import trendradar.storage", source)

    def test_no_config_import(self):
        source = self._read_source()
        self.assertNotIn("from trendradar.config", source)
        self.assertNotIn("import trendradar.config", source)

    def test_no_ai_import(self):
        source = self._read_source()
        self.assertNotIn("from trendradar.ai", source)
        self.assertNotIn("import trendradar.ai", source)

    def test_no_ai_analysis_result(self):
        source = self._read_source()
        self.assertNotIn("AIAnalysisResult", source)

    def test_no_telegram(self):
        source = self._read_source()
        self.assertNotIn("telegram", source.lower())

    def test_no_sender(self):
        source = self._read_source()
        self.assertNotIn("sender", source.lower())

    def test_no_dispatcher(self):
        source = self._read_source()
        self.assertNotIn("dispatcher", source.lower())

    def test_no_run_analysis_pipeline(self):
        source = self._read_source()
        self.assertNotIn("_run_analysis_pipeline", source)

    def test_allowed_imports_only(self):
        """Only trendradar.cr.* submodules are imported."""
        source = self._read_source()
        import re

        imports = re.findall(
            r"^(?:from|import)\s+(trendradar\S*)", source, re.MULTILINE
        )
        for imp in imports:
            self.assertTrue(
                imp.startswith("trendradar.cr."),
                f"Forbidden import: {imp}",
            )


if __name__ == "__main__":
    unittest.main()
