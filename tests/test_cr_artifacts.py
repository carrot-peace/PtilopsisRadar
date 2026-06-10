# coding=utf-8
"""
Tests for CR artifact path resolver / writer (PR9h) and combined render/write
helper (PR9i / Part D).

All filesystem writes are confined to ``tempfile.TemporaryDirectory()``.
"""

import tempfile
import unittest
from pathlib import Path

from trendradar.cr.artifacts import (
    CRArtifactConfig,
    CRArtifactPaths,
    render_and_write_cr_artifacts,
    resolve_cr_artifact_paths,
    sanitize_artifact_label,
    write_cr_artifact_bundle,
    write_cr_html_artifact,
    write_cr_markdown_audit_artifact,
    write_text_artifact,
)
from trendradar.cr.decision import (
    CRDecision,
    DECISION_SUPPRESS,
    DECISION_URGENT,
)
from trendradar.cr.models import CRCandidate, CRSourceItem
from trendradar.cr.presentation import CRPresentedCandidate
from trendradar.cr.scoring import CRScoreResult


# ---------------------------------------------------------------------------
# Test helpers
# ---------------------------------------------------------------------------


def _make_presented(
    candidate_id: str = "c1",
    cluster_key: str = "key1",
    display_title: str = "Topic A",
    decision_level: str = DECISION_URGENT,
    total_score: float = 90.0,
    suppress_labels: list | None = None,
) -> CRPresentedCandidate:
    si = CRSourceItem(
        title="Source A",
        url="https://source.example.com",
        source_type="hotlist",
        source_name="weibo",
        source_id="weibo",
        current_rank=3,
        normalized_rank=1,
        is_new=True,
    )
    cand = CRCandidate(
        candidate_id=candidate_id,
        cluster_key=cluster_key,
        display_title=display_title,
        representative_url="https://example.com",
        source_items=[si],
    )
    sr = CRScoreResult(
        candidate_id=candidate_id,
        cluster_key=cluster_key,
        profile_version="cr-score-v0.1",
        total_score=total_score,
        trigger_reasons=["high heat"],
        debug={"profile_version": "cr-score-v0.1", "total_raw": total_score},
    )
    dec = CRDecision(
        candidate_id=candidate_id,
        cluster_key=cluster_key,
        profile_version="cr-score-v0.1",
        policy_version="cr-decision-v0.1",
        level=decision_level,
        total_score=total_score,
        suppress_labels=suppress_labels or [],
        trigger_reasons=["high heat"],
        debug={"policy_version": "cr-decision-v0.1"},
    )
    return CRPresentedCandidate(
        candidate=cand,
        score_result=sr,
        decision=dec,
        candidate_id=candidate_id,
        cluster_key=cluster_key,
        display_title=display_title,
        representative_url="https://example.com",
        decision_level=decision_level,
        total_score=total_score,
        trigger_reasons=["high heat"],
        suppress_labels=suppress_labels or [],
    )


# ===========================================================================
# A. Config Defaults
# ===========================================================================


class TestConfigDefaults(unittest.TestCase):
    """A. CRArtifactConfig default values."""

    def test_root_dir_default(self):
        self.assertEqual(Path(CRArtifactConfig().root_dir), Path("output/cr"))

    def test_markdown_archive_dirname_default(self):
        self.assertEqual(
            CRArtifactConfig().markdown_archive_dirname, "archive/markdown"
        )

    def test_html_archive_dirname_default(self):
        self.assertEqual(
            CRArtifactConfig().html_archive_dirname, "archive/html"
        )

    def test_latest_dirname_default(self):
        self.assertEqual(CRArtifactConfig().latest_dirname, "latest")

    def test_markdown_filename_default(self):
        self.assertEqual(CRArtifactConfig().markdown_filename, "cr_markdown.md")

    def test_html_filename_default(self):
        self.assertEqual(CRArtifactConfig().html_filename, "cr.html")

    def test_encoding_default(self):
        self.assertEqual(CRArtifactConfig().encoding, "utf-8")

    def test_config_is_frozen(self):
        cfg = CRArtifactConfig()
        with self.assertRaises(Exception):
            cfg.encoding = "latin-1"  # type: ignore[misc]


# ===========================================================================
# B. Label Sanitization
# ===========================================================================


class TestLabelSanitization(unittest.TestCase):
    """B. sanitize_artifact_label behavior."""

    def test_space_and_colon_to_dash(self):
        self.assertEqual(
            sanitize_artifact_label("2026-06-09 23:30"), "2026-06-09-23-30"
        )

    def test_slash_to_dash_no_slash(self):
        result = sanitize_artifact_label("2026/06/09 23:30")
        self.assertEqual(result, "2026-06-09-23-30")
        self.assertNotIn("/", result)

    def test_surrounding_whitespace_stripped(self):
        self.assertEqual(sanitize_artifact_label(" current run "), "current-run")

    def test_empty_returns_run(self):
        self.assertEqual(sanitize_artifact_label(""), "run")

    def test_single_dot_returns_run(self):
        self.assertEqual(sanitize_artifact_label("."), "run")

    def test_double_dot_returns_run(self):
        self.assertEqual(sanitize_artifact_label(".."), "run")

    def test_backslash_replaced(self):
        result = sanitize_artifact_label("a\\b")
        self.assertNotIn("\\", result)
        self.assertEqual(result, "a-b")

    def test_repeated_separators_collapse(self):
        self.assertEqual(sanitize_artifact_label("a///b"), "a-b")
        self.assertEqual(sanitize_artifact_label("a   b"), "a-b")

    def test_parent_traversal_not_created(self):
        result = sanitize_artifact_label("../../bad")
        self.assertNotIn("/", result)
        self.assertNotIn("\\", result)
        self.assertNotEqual(result, "..")

    def test_cjk_survives_or_degrades_safely(self):
        result = sanitize_artifact_label("热点 新闻")
        self.assertNotIn("/", result)
        self.assertNotIn("\\", result)
        self.assertTrue(result)  # non-empty

    def test_result_never_contains_separators(self):
        for label in [
            "a/b\\c",
            "//\\\\",
            "  /x/  ",
            "2026/06/09\\23:30",
            "../../../etc/passwd",
        ]:
            result = sanitize_artifact_label(label)
            self.assertNotIn("/", result)
            self.assertNotIn("\\", result)


# ===========================================================================
# C. Path Resolution
# ===========================================================================


class TestPathResolution(unittest.TestCase):
    """C. resolve_cr_artifact_paths layout and behavior."""

    def test_archive_and_latest_layout(self):
        with tempfile.TemporaryDirectory() as d:
            cfg = CRArtifactConfig(root_dir=d)
            paths = resolve_cr_artifact_paths(
                run_label="2026-06-09 23:30", config=cfg
            )
            root = Path(d)
            self.assertEqual(
                paths.markdown_archive_path,
                root / "archive" / "markdown" / "2026-06-09-23-30.md",
            )
            self.assertEqual(
                paths.html_archive_path,
                root / "archive" / "html" / "2026-06-09-23-30.html",
            )
            self.assertEqual(
                paths.latest_markdown_path, root / "latest" / "cr_markdown.md"
            )
            self.assertEqual(
                paths.latest_html_path, root / "latest" / "cr.html"
            )

    def test_resolver_does_not_create_directories(self):
        with tempfile.TemporaryDirectory() as d:
            cfg = CRArtifactConfig(root_dir=Path(d) / "nested")
            resolve_cr_artifact_paths(run_label="run", config=cfg)
            self.assertFalse((Path(d) / "nested").exists())

    def test_paths_under_root(self):
        with tempfile.TemporaryDirectory() as d:
            cfg = CRArtifactConfig(root_dir=d)
            paths = resolve_cr_artifact_paths(
                run_label="../../escape", config=cfg
            )
            root = Path(d).resolve()
            for p in (
                paths.markdown_archive_path,
                paths.html_archive_path,
                paths.latest_markdown_path,
                paths.latest_html_path,
            ):
                self.assertTrue(
                    str(p.resolve()).startswith(str(root)),
                    f"{p} not under {root}",
                )

    def test_same_run_label_same_paths(self):
        with tempfile.TemporaryDirectory() as d:
            cfg = CRArtifactConfig(root_dir=d)
            a = resolve_cr_artifact_paths(run_label="R1", config=cfg)
            b = resolve_cr_artifact_paths(run_label="R1", config=cfg)
            self.assertEqual(a, b)

    def test_different_run_label_different_archive_same_latest(self):
        with tempfile.TemporaryDirectory() as d:
            cfg = CRArtifactConfig(root_dir=d)
            a = resolve_cr_artifact_paths(run_label="R1", config=cfg)
            b = resolve_cr_artifact_paths(run_label="R2", config=cfg)
            self.assertNotEqual(a.markdown_archive_path, b.markdown_archive_path)
            self.assertNotEqual(a.html_archive_path, b.html_archive_path)
            self.assertEqual(a.latest_markdown_path, b.latest_markdown_path)
            self.assertEqual(a.latest_html_path, b.latest_html_path)

    def test_default_config_used_when_none(self):
        paths = resolve_cr_artifact_paths(run_label="R1")
        self.assertEqual(
            paths.markdown_archive_path,
            Path("output/cr") / "archive" / "markdown" / "R1.md",
        )

    def test_str_root_dir_normalized_to_path(self):
        paths = resolve_cr_artifact_paths(
            run_label="R1", config=CRArtifactConfig(root_dir="some/root")
        )
        self.assertIsInstance(paths.markdown_archive_path, Path)
        self.assertEqual(
            paths.latest_html_path, Path("some/root") / "latest" / "cr.html"
        )


# ===========================================================================
# D. Write Text Artifact
# ===========================================================================


class TestWriteTextArtifact(unittest.TestCase):
    """D. write_text_artifact behavior."""

    def test_creates_parent_directories(self):
        with tempfile.TemporaryDirectory() as d:
            target = Path(d) / "a" / "b" / "c.txt"
            write_text_artifact(target, "hello")
            self.assertTrue(target.exists())

    def test_writes_content(self):
        with tempfile.TemporaryDirectory() as d:
            target = Path(d) / "f.txt"
            write_text_artifact(target, "hello world")
            self.assertEqual(target.read_text(encoding="utf-8"), "hello world")

    def test_returns_path(self):
        with tempfile.TemporaryDirectory() as d:
            target = Path(d) / "f.txt"
            result = write_text_artifact(target, "x")
            self.assertIsInstance(result, Path)
            self.assertEqual(result, target)

    def test_accepts_str_path(self):
        with tempfile.TemporaryDirectory() as d:
            target = str(Path(d) / "f.txt")
            result = write_text_artifact(target, "x")
            self.assertIsInstance(result, Path)

    def test_preserves_content_exactly(self):
        content = "line1\nline2\n  spaced  \ttab\nunicode: 热点\n"
        with tempfile.TemporaryDirectory() as d:
            target = Path(d) / "f.txt"
            write_text_artifact(target, content)
            self.assertEqual(
                target.read_text(encoding="utf-8", newline=""), content
            )

    def test_uses_utf8_by_default(self):
        content = "热点新闻"
        with tempfile.TemporaryDirectory() as d:
            target = Path(d) / "f.txt"
            write_text_artifact(target, content)
            self.assertEqual(target.read_bytes(), content.encode("utf-8"))

    def test_overwrites_existing_file(self):
        with tempfile.TemporaryDirectory() as d:
            target = Path(d) / "f.txt"
            write_text_artifact(target, "first")
            write_text_artifact(target, "second")
            self.assertEqual(target.read_text(encoding="utf-8"), "second")


# ===========================================================================
# E. Write Artifact Bundle
# ===========================================================================


class TestWriteArtifactBundle(unittest.TestCase):
    """E. write_cr_artifact_bundle behavior."""

    def test_writes_all_four_files(self):
        with tempfile.TemporaryDirectory() as d:
            cfg = CRArtifactConfig(root_dir=d)
            paths = write_cr_artifact_bundle(
                markdown_text="MD-BODY",
                html_text="HTML-BODY",
                run_label="R1",
                config=cfg,
            )
            self.assertTrue(paths.markdown_archive_path.exists())
            self.assertTrue(paths.html_archive_path.exists())
            self.assertTrue(paths.latest_markdown_path.exists())
            self.assertTrue(paths.latest_html_path.exists())

    def test_files_contain_expected_content(self):
        with tempfile.TemporaryDirectory() as d:
            cfg = CRArtifactConfig(root_dir=d)
            paths = write_cr_artifact_bundle(
                markdown_text="MD-BODY",
                html_text="HTML-BODY",
                run_label="R1",
                config=cfg,
            )
            self.assertEqual(
                paths.markdown_archive_path.read_text(encoding="utf-8"), "MD-BODY"
            )
            self.assertEqual(
                paths.latest_markdown_path.read_text(encoding="utf-8"), "MD-BODY"
            )
            self.assertEqual(
                paths.html_archive_path.read_text(encoding="utf-8"), "HTML-BODY"
            )
            self.assertEqual(
                paths.latest_html_path.read_text(encoding="utf-8"), "HTML-BODY"
            )

    def test_returns_all_paths(self):
        with tempfile.TemporaryDirectory() as d:
            cfg = CRArtifactConfig(root_dir=d)
            paths = write_cr_artifact_bundle(
                markdown_text="m", html_text="h", run_label="R1", config=cfg
            )
            self.assertIsInstance(paths, CRArtifactPaths)

    def test_creates_directories(self):
        with tempfile.TemporaryDirectory() as d:
            cfg = CRArtifactConfig(root_dir=Path(d) / "fresh")
            write_cr_artifact_bundle(
                markdown_text="m", html_text="h", run_label="R1", config=cfg
            )
            self.assertTrue((Path(d) / "fresh" / "archive" / "markdown").is_dir())
            self.assertTrue((Path(d) / "fresh" / "archive" / "html").is_dir())
            self.assertTrue((Path(d) / "fresh" / "latest").is_dir())

    def test_same_run_label_overwrites_archive(self):
        with tempfile.TemporaryDirectory() as d:
            cfg = CRArtifactConfig(root_dir=d)
            write_cr_artifact_bundle(
                markdown_text="first", html_text="h1", run_label="R1", config=cfg
            )
            paths = write_cr_artifact_bundle(
                markdown_text="second", html_text="h2", run_label="R1", config=cfg
            )
            self.assertEqual(
                paths.markdown_archive_path.read_text(encoding="utf-8"), "second"
            )

    def test_different_run_label_separate_archive(self):
        with tempfile.TemporaryDirectory() as d:
            cfg = CRArtifactConfig(root_dir=d)
            p1 = write_cr_artifact_bundle(
                markdown_text="one", html_text="h1", run_label="R1", config=cfg
            )
            p2 = write_cr_artifact_bundle(
                markdown_text="two", html_text="h2", run_label="R2", config=cfg
            )
            self.assertNotEqual(
                p1.markdown_archive_path, p2.markdown_archive_path
            )
            self.assertEqual(
                p1.markdown_archive_path.read_text(encoding="utf-8"), "one"
            )
            self.assertEqual(
                p2.markdown_archive_path.read_text(encoding="utf-8"), "two"
            )

    def test_latest_is_overwritten(self):
        with tempfile.TemporaryDirectory() as d:
            cfg = CRArtifactConfig(root_dir=d)
            write_cr_artifact_bundle(
                markdown_text="one", html_text="h1", run_label="R1", config=cfg
            )
            paths = write_cr_artifact_bundle(
                markdown_text="two", html_text="h2", run_label="R2", config=cfg
            )
            self.assertEqual(
                paths.latest_markdown_path.read_text(encoding="utf-8"), "two"
            )
            self.assertEqual(
                paths.latest_html_path.read_text(encoding="utf-8"), "h2"
            )


# ===========================================================================
# F. Single-format Writers
# ===========================================================================


class TestSingleFormatWriters(unittest.TestCase):
    """F. write_cr_markdown_audit_artifact / write_cr_html_artifact."""

    def test_markdown_only_writes_markdown_files(self):
        with tempfile.TemporaryDirectory() as d:
            cfg = CRArtifactConfig(root_dir=d)
            paths = write_cr_markdown_audit_artifact(
                "MD", run_label="R1", config=cfg
            )
            self.assertTrue(paths.markdown_archive_path.exists())
            self.assertTrue(paths.latest_markdown_path.exists())
            # HTML files not written.
            self.assertFalse(paths.html_archive_path.exists())
            self.assertFalse(paths.latest_html_path.exists())

    def test_markdown_only_returns_all_four_paths(self):
        with tempfile.TemporaryDirectory() as d:
            cfg = CRArtifactConfig(root_dir=d)
            paths = write_cr_markdown_audit_artifact(
                "MD", run_label="R1", config=cfg
            )
            self.assertIsInstance(paths, CRArtifactPaths)
            self.assertTrue(str(paths.html_archive_path).endswith(".html"))

    def test_html_only_writes_html_files(self):
        with tempfile.TemporaryDirectory() as d:
            cfg = CRArtifactConfig(root_dir=d)
            paths = write_cr_html_artifact("HTML", run_label="R1", config=cfg)
            self.assertTrue(paths.html_archive_path.exists())
            self.assertTrue(paths.latest_html_path.exists())
            # Markdown files not written.
            self.assertFalse(paths.markdown_archive_path.exists())
            self.assertFalse(paths.latest_markdown_path.exists())

    def test_html_only_returns_all_four_paths(self):
        with tempfile.TemporaryDirectory() as d:
            cfg = CRArtifactConfig(root_dir=d)
            paths = write_cr_html_artifact("HTML", run_label="R1", config=cfg)
            self.assertIsInstance(paths, CRArtifactPaths)
            self.assertTrue(str(paths.markdown_archive_path).endswith(".md"))


# ===========================================================================
# G. Combined Render + Write
# ===========================================================================


class TestCombinedRenderWrite(unittest.TestCase):
    """G. render_and_write_cr_artifacts behavior."""

    def test_writes_markdown_and_html(self):
        with tempfile.TemporaryDirectory() as d:
            cfg = CRArtifactConfig(root_dir=d)
            cands = [
                _make_presented("u1", "k1", "Urgent Topic", DECISION_URGENT, 90.0),
                _make_presented(
                    "s1", "k2", "Bad Topic", DECISION_SUPPRESS, 95.0,
                    suppress_labels=["off_topic"],
                ),
            ]
            paths = render_and_write_cr_artifacts(
                cands, run_label="2026-06-09 23:30", artifact_config=cfg
            )
            self.assertTrue(paths.markdown_archive_path.exists())
            self.assertTrue(paths.html_archive_path.exists())
            self.assertTrue(paths.latest_markdown_path.exists())
            self.assertTrue(paths.latest_html_path.exists())

    def test_archive_md_contains_markdown_title(self):
        with tempfile.TemporaryDirectory() as d:
            cfg = CRArtifactConfig(root_dir=d)
            cands = [_make_presented()]
            paths = render_and_write_cr_artifacts(
                cands, run_label="R1", artifact_config=cfg
            )
            md = paths.markdown_archive_path.read_text(encoding="utf-8")
            self.assertIn("# Ptilopsis Radar｜CR Markdown Audit", md)

    def test_archive_html_contains_html_title(self):
        with tempfile.TemporaryDirectory() as d:
            cfg = CRArtifactConfig(root_dir=d)
            cands = [_make_presented()]
            paths = render_and_write_cr_artifacts(
                cands, run_label="R1", artifact_config=cfg
            )
            html = paths.html_archive_path.read_text(encoding="utf-8")
            self.assertIn("<!doctype html>", html)
            self.assertIn(
                "<title>Ptilopsis Radar｜CR HTML Audit</title>", html
            )

    def test_high_score_suppress_count_propagates(self):
        with tempfile.TemporaryDirectory() as d:
            cfg = CRArtifactConfig(root_dir=d)
            cands = [
                _make_presented(
                    "s1", "k1", "Bad", DECISION_SUPPRESS, 90.0,
                    suppress_labels=["x"],
                )
            ]
            paths = render_and_write_cr_artifacts(
                cands, run_label="R1", artifact_config=cfg
            )
            md = paths.markdown_archive_path.read_text(encoding="utf-8")
            html = paths.html_archive_path.read_text(encoding="utf-8")
            self.assertIn("High-score suppressed candidates: 1", md)
            self.assertIn(
                "High-score suppressed candidates:</strong> 1", html
            )


# ===========================================================================
# H. No Forbidden Behavior
# ===========================================================================


class TestNoForbiddenBehavior(unittest.TestCase):
    """H. artifacts.py does not import forbidden modules."""

    def _read_source(self) -> str:
        import trendradar.cr.artifacts as mod

        source_file = mod.__file__
        assert source_file is not None
        with open(source_file) as f:
            return f.read()

    def test_no_telegram_import(self):
        source = self._read_source()
        self.assertNotIn("telegram", source.lower())

    def test_no_report_archive_import(self):
        source = self._read_source()
        self.assertNotIn("from trendradar.report", source)
        self.assertNotIn("from trendradar.archive", source)
        self.assertNotIn("import trendradar.report", source)

    def test_no_storage_config_import(self):
        source = self._read_source()
        self.assertNotIn("from trendradar.storage", source)
        self.assertNotIn("from trendradar.config", source)

    def test_no_notification_import(self):
        source = self._read_source()
        self.assertNotIn("from trendradar.notification", source)

    def test_no_ai_analysis_result(self):
        source = self._read_source()
        self.assertNotIn("AIAnalysisResult", source)

    def test_no_sender_dispatcher(self):
        source = self._read_source()
        self.assertNotIn("sender", source.lower())
        self.assertNotIn("dispatcher", source.lower())

    def test_no_runtime_import(self):
        source = self._read_source()
        self.assertNotIn("from trendradar.__main__", source)
        self.assertNotIn("_run_analysis_pipeline", source)


if __name__ == "__main__":
    unittest.main()
