# coding=utf-8
"""
PR9k: CR runtime dry-run hook tests.

Covers:
  - CRRuntimeDryRunResult model shape
  - adapter composition (hotlist-only, rss-only, combined, empty)
  - pipeline + artifact write via temp dirs only
  - determinism + input non-mutation
  - source boundary (no notification / storage / config / ai / telegram tokens)
  - __main__ hook trigger is PTILOPSIS_CR_DRY_RUN only

No network, no real crawlers, no Telegram, no real output directories.
"""

import copy
import os
import sys
import tempfile
import unittest
from pathlib import Path

# Ensure project root is on path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from trendradar.cr.artifacts import CRArtifactConfig, CRArtifactPaths
from trendradar.cr.dispatch_plan import CRDispatchPlan
from trendradar.cr.pipeline import CRPipelineResult
from trendradar.cr.runtime_dry_run import (
    CRRuntimeDryRunResult,
    build_and_write_cr_runtime_dry_run,
)


# ---------------------------------------------------------------------------
# Fixtures — shaped like existing CR adapter tests
# ---------------------------------------------------------------------------


def _make_hotlist_item(
    title="Test Title",
    source_name="weibo",
    source_id="weibo",
    ranks=None,
    rank_timeline=None,
    first_time="09:30",
    last_time="12:00",
    count=3,
    is_new=False,
    url="https://example.com",
):
    """Build a hotlist stats title item (mimics count_word_frequency output)."""
    if ranks is None:
        ranks = [5]
    return {
        "title": title,
        "source_name": source_name,
        "source_id": source_id,
        "ranks": ranks,
        "count": count,
        "first_time": first_time,
        "last_time": last_time,
        "url": url,
        "mobileUrl": "",
        "is_new": is_new,
        "rank_timeline": rank_timeline or [],
    }


def _make_rss_item(
    title="RSS Title",
    source_name="Hacker News",
    feed_id="hacker-news",
    ranks=None,
    first_time="2026-06-08T08:00:00+08:00",
    last_time="",
    count=1,
    is_new=False,
    url="https://hn.example.com/1",
    published_at="2026-06-08T08:00:00+08:00",
    summary="A summary",
    author="Author Name",
):
    """Build an RSS stats title item (mimics count_rss_frequency output)."""
    if ranks is None:
        ranks = [1]
    return {
        "title": title,
        "source_name": source_name,
        "feed_id": feed_id,
        "ranks": ranks,
        "count": count,
        "first_time": first_time,
        "last_time": last_time,
        "url": url,
        "mobile_url": "",
        "is_new": is_new,
        "published_at": published_at,
        "summary": summary,
        "author": author,
    }


def _hotlist_stats():
    return [
        {
            "word": "AI",
            "titles": [
                _make_hotlist_item(title="AI Title One", ranks=[3]),
                _make_hotlist_item(title="AI Title Two", ranks=[8]),
            ],
            "count": 2,
            "position": 0,
        },
        {
            "word": "Finance",
            "titles": [_make_hotlist_item(title="Fin Title", ranks=[12])],
            "count": 1,
            "position": 1,
        },
    ]


def _rss_stats():
    return [
        {
            "word": "Tech",
            "titles": [_make_rss_item(title="RSS Tech One")],
            "count": 1,
            "position": 0,
        },
    ]


def _artifact_config(root: str) -> CRArtifactConfig:
    return CRArtifactConfig(root_dir=Path(root))


# ---------------------------------------------------------------------------
# Test Group A — Runtime Dry-Run Model
# ---------------------------------------------------------------------------


class TestRuntimeDryRunModel(unittest.TestCase):
    def test_result_is_frozen(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = build_and_write_cr_runtime_dry_run(
                hotlist_stats=_hotlist_stats(),
                run_label="run-a",
                artifact_config=_artifact_config(tmp),
            )
            with self.assertRaises(Exception):
                result.primitives = ()  # type: ignore[misc]

    def test_primitives_is_tuple(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = build_and_write_cr_runtime_dry_run(
                hotlist_stats=_hotlist_stats(),
                run_label="run-a",
                artifact_config=_artifact_config(tmp),
            )
            self.assertIsInstance(result.primitives, tuple)

    def test_pipeline_is_pipeline_result(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = build_and_write_cr_runtime_dry_run(
                hotlist_stats=_hotlist_stats(),
                run_label="run-a",
                artifact_config=_artifact_config(tmp),
            )
            self.assertIsInstance(result.pipeline, CRPipelineResult)

    def test_artifact_paths_is_artifact_paths(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = build_and_write_cr_runtime_dry_run(
                hotlist_stats=_hotlist_stats(),
                run_label="run-a",
                artifact_config=_artifact_config(tmp),
            )
            self.assertIsInstance(result.artifact_paths, CRArtifactPaths)

    def test_dispatch_plan_is_dispatch_plan(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = build_and_write_cr_runtime_dry_run(
                hotlist_stats=_hotlist_stats(),
                run_label="run-a",
                artifact_config=_artifact_config(tmp),
            )
            self.assertIsInstance(result.dispatch_plan, CRDispatchPlan)
            # Dry-run is pure planning — plan refers to the same run.
            self.assertEqual(
                result.dispatch_plan.run_label, result.pipeline.run_label
            )


# ---------------------------------------------------------------------------
# Test Group B — Adapter Composition
# ---------------------------------------------------------------------------


class TestAdapterComposition(unittest.TestCase):
    def test_hotlist_only_produces_primitives(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = build_and_write_cr_runtime_dry_run(
                hotlist_stats=_hotlist_stats(),
                run_label="run-b",
                artifact_config=_artifact_config(tmp),
            )
            self.assertGreater(len(result.primitives), 0)
            self.assertTrue(
                all(p.record_source == "hotlist_stats" for p in result.primitives)
            )

    def test_rss_only_produces_primitives(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = build_and_write_cr_runtime_dry_run(
                rss_stats=_rss_stats(),
                run_label="run-b",
                artifact_config=_artifact_config(tmp),
            )
            self.assertGreater(len(result.primitives), 0)
            self.assertTrue(
                all(p.record_source == "rss_stats" for p in result.primitives)
            )

    def test_combined_deterministic_order_hotlist_first(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = build_and_write_cr_runtime_dry_run(
                hotlist_stats=_hotlist_stats(),
                rss_stats=_rss_stats(),
                run_label="run-b",
                artifact_config=_artifact_config(tmp),
            )
            sources = [p.record_source for p in result.primitives]
            # hotlist primitives first, rss primitives second
            self.assertEqual(sources.count("hotlist_stats"), 2)
            self.assertEqual(sources.count("rss_stats"), 1)
            first_rss = sources.index("rss_stats")
            self.assertTrue(all(s == "hotlist_stats" for s in sources[:first_rss]))
            self.assertTrue(all(s == "rss_stats" for s in sources[first_rss:]))

    def test_empty_input_empty_primitives_valid_pipeline(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = build_and_write_cr_runtime_dry_run(
                run_label="run-b",
                artifact_config=_artifact_config(tmp),
            )
            self.assertEqual(result.primitives, ())
            self.assertIsInstance(result.pipeline, CRPipelineResult)
            self.assertEqual(result.pipeline.primitives, ())


# ---------------------------------------------------------------------------
# Test Group C — Pipeline + Artifact Write
# ---------------------------------------------------------------------------


class TestPipelineArtifactWrite(unittest.TestCase):
    def _run(self, tmp):
        return build_and_write_cr_runtime_dry_run(
            hotlist_stats=_hotlist_stats(),
            rss_stats=_rss_stats(),
            run_label="run-c",
            artifact_config=_artifact_config(tmp),
        )

    def test_writes_markdown_archive(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = self._run(tmp)
            self.assertTrue(result.artifact_paths.markdown_archive_path.exists())

    def test_writes_html_archive(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = self._run(tmp)
            self.assertTrue(result.artifact_paths.html_archive_path.exists())

    def test_writes_latest_markdown(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = self._run(tmp)
            self.assertTrue(result.artifact_paths.latest_markdown_path.exists())

    def test_writes_latest_html(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = self._run(tmp)
            self.assertTrue(result.artifact_paths.latest_html_path.exists())

    def test_markdown_contains_audit_title(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = self._run(tmp)
            text = result.artifact_paths.latest_markdown_path.read_text(
                encoding="utf-8"
            )
            self.assertIn("CR Markdown Audit", text)
            self.assertEqual(text, result.pipeline.markdown_audit_text)

    def test_html_contains_doctype(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = self._run(tmp)
            text = result.artifact_paths.latest_html_path.read_text(
                encoding="utf-8"
            )
            self.assertIn("<!doctype html>", text.lower())

    def test_empty_input_still_writes_artifacts(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = build_and_write_cr_runtime_dry_run(
                run_label="run-c-empty",
                artifact_config=_artifact_config(tmp),
            )
            self.assertTrue(result.artifact_paths.markdown_archive_path.exists())
            self.assertTrue(result.artifact_paths.html_archive_path.exists())
            self.assertTrue(result.artifact_paths.latest_markdown_path.exists())
            self.assertTrue(result.artifact_paths.latest_html_path.exists())


# ---------------------------------------------------------------------------
# Test Group D — Determinism
# ---------------------------------------------------------------------------


class TestDeterminism(unittest.TestCase):
    def test_same_input_same_cr_a_text(self):
        with tempfile.TemporaryDirectory() as t1, tempfile.TemporaryDirectory() as t2:
            r1 = build_and_write_cr_runtime_dry_run(
                hotlist_stats=_hotlist_stats(),
                rss_stats=_rss_stats(),
                run_label="dt",
                artifact_config=_artifact_config(t1),
            )
            r2 = build_and_write_cr_runtime_dry_run(
                hotlist_stats=_hotlist_stats(),
                rss_stats=_rss_stats(),
                run_label="dt",
                artifact_config=_artifact_config(t2),
            )
            self.assertEqual(r1.pipeline.cr_a_text, r2.pipeline.cr_a_text)

    def test_same_input_same_markdown(self):
        with tempfile.TemporaryDirectory() as t1, tempfile.TemporaryDirectory() as t2:
            r1 = build_and_write_cr_runtime_dry_run(
                hotlist_stats=_hotlist_stats(),
                run_label="dt",
                artifact_config=_artifact_config(t1),
            )
            r2 = build_and_write_cr_runtime_dry_run(
                hotlist_stats=_hotlist_stats(),
                run_label="dt",
                artifact_config=_artifact_config(t2),
            )
            self.assertEqual(
                r1.pipeline.markdown_audit_text, r2.pipeline.markdown_audit_text
            )

    def test_same_input_same_html(self):
        with tempfile.TemporaryDirectory() as t1, tempfile.TemporaryDirectory() as t2:
            r1 = build_and_write_cr_runtime_dry_run(
                hotlist_stats=_hotlist_stats(),
                run_label="dt",
                artifact_config=_artifact_config(t1),
            )
            r2 = build_and_write_cr_runtime_dry_run(
                hotlist_stats=_hotlist_stats(),
                run_label="dt",
                artifact_config=_artifact_config(t2),
            )
            self.assertEqual(
                r1.pipeline.html_audit_text, r2.pipeline.html_audit_text
            )

    def test_input_stats_not_mutated(self):
        hotlist = _hotlist_stats()
        rss = _rss_stats()
        hotlist_snapshot = copy.deepcopy(hotlist)
        rss_snapshot = copy.deepcopy(rss)
        with tempfile.TemporaryDirectory() as tmp:
            build_and_write_cr_runtime_dry_run(
                hotlist_stats=hotlist,
                rss_stats=rss,
                run_label="dt",
                artifact_config=_artifact_config(tmp),
            )
        self.assertEqual(hotlist, hotlist_snapshot)
        self.assertEqual(rss, rss_snapshot)


# ---------------------------------------------------------------------------
# Test Group E — Boundary
# ---------------------------------------------------------------------------


class TestSourceBoundary(unittest.TestCase):
    """runtime_dry_run.py must not import / reference forbidden subsystems."""

    FORBIDDEN = (
        "trendradar.notification",
        "trendradar.storage",
        "trendradar.config",
        "trendradar.ai",
        "AIAnalysisResult",
        "telegram",
        "sender",
        "dispatcher",
        "cooldown",
        "dedupe",
        "alert_state",
    )

    def _module_source(self) -> str:
        import trendradar.cr.runtime_dry_run as mod

        return Path(mod.__file__).read_text(encoding="utf-8")

    def test_no_forbidden_tokens(self):
        source = self._module_source()
        for token in self.FORBIDDEN:
            self.assertNotIn(
                token, source, f"forbidden token {token!r} present in module"
            )


class TestMainHookTrigger(unittest.TestCase):
    """__main__ CR dry-run hook must be gated solely by PTILOPSIS_CR_DRY_RUN."""

    def _main_source(self) -> str:
        # Read by path (no import) so the check does not depend on the runtime's
        # third-party deps being installed.
        main_path = (
            Path(__file__).resolve().parent.parent
            / "trendradar"
            / "__main__.py"
        )
        return main_path.read_text(encoding="utf-8")

    def test_dry_run_env_trigger_present(self):
        source = self._main_source()
        self.assertIn("PTILOPSIS_CR_DRY_RUN", source)

    def test_dry_run_is_only_cr_trigger(self):
        source = self._main_source()
        # Exactly one env gate introduced for CR dry-run.
        self.assertEqual(
            source.count('os.environ.get("PTILOPSIS_CR_DRY_RUN")'), 1
        )
        # No other PTILOPSIS_CR_* env trigger is introduced.
        self.assertNotIn("PTILOPSIS_CR_", source.replace("PTILOPSIS_CR_DRY_RUN", ""))
        # The gate guards the dry-run bridge call.
        self.assertIn("build_and_write_cr_runtime_dry_run", source)


if __name__ == "__main__":
    unittest.main()
