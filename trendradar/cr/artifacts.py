# coding=utf-8
"""
CR artifact path resolver / writer (PR9h) + combined render/write helper.

This layer writes already-rendered Markdown / HTML strings to deterministic CR
artifact paths under a dedicated CR artifact root.  Purely internal — it does
NOT integrate with runtime, the existing report / archive modules, storage,
config.yaml, messaging delivery, or AI result models.  It does NOT implement
retention cleanup or daily HTML consolidation.

Design reference: PR9h (paths / writer), PR9i (combined render/write helper).
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from pathlib import Path

from trendradar.cr.html import CRHTMLRenderConfig, render_cr_html_audit
from trendradar.cr.markdown import (
    CRMarkdownRenderConfig,
    render_cr_markdown_audit,
)
from trendradar.cr.presentation import CRPresentedCandidate


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class CRArtifactConfig:
    """Configuration for CR artifact path layout and writing.

    ``root_dir`` is dedicated to CR artifacts only; it must not reuse existing
    report paths.  No config.yaml wiring.
    """

    root_dir: Path | str = Path("output/cr")
    markdown_archive_dirname: str = "archive/markdown"
    html_archive_dirname: str = "archive/html"
    latest_dirname: str = "latest"
    markdown_filename: str = "cr_markdown.md"
    html_filename: str = "cr.html"
    encoding: str = "utf-8"


# ---------------------------------------------------------------------------
# Paths model
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class CRArtifactPaths:
    """Resolved CR artifact paths (v0.1 layout).

    Does NOT include daily consolidated paths.
    """

    markdown_archive_path: Path
    html_archive_path: Path
    latest_markdown_path: Path
    latest_html_path: Path


# ---------------------------------------------------------------------------
# Safe slug / filename helper
# ---------------------------------------------------------------------------

_REPEAT_DASH_RE = re.compile(r"-+")


def sanitize_artifact_label(label: str) -> str:
    """Sanitize a run label into a filesystem-safe slug.

    Rules:
      - NFKC-normalize and strip surrounding whitespace.
      - Replace path separators (``/`` ``\\``), whitespace, and colon-like
        separators with ``-``.
      - Keep ASCII letters / digits / ``_`` / ``-`` / ``.`` and non-ASCII
        alphanumerics (e.g. CJK) if safe; replace anything else with ``-``.
      - Collapse repeated ``-`` and strip leading/trailing ``-``.
      - Never contains ``/`` or ``\\``.
      - Never returns an empty string, ``"."``, or ``".."`` — returns
        ``"run"`` in those cases.

    Deterministic: does NOT use current time or random values.
    """
    normalized = unicodedata.normalize("NFKC", label).strip()

    out: list[str] = []
    for ch in normalized:
        if ch in ("/", "\\"):
            out.append("-")
        elif ch.isspace():
            out.append("-")
        elif ch in (":", ";", "|"):
            out.append("-")
        elif ch in ("_", "-", "."):
            out.append(ch)
        elif ch.isascii():
            if ch.isalnum():
                out.append(ch)
            else:
                out.append("-")
        elif ch.isalnum():
            # Non-ASCII alphanumerics (CJK, accented letters, ...) — keep.
            out.append(ch)
        else:
            out.append("-")

    slug = _REPEAT_DASH_RE.sub("-", "".join(out)).strip("-")

    if not slug or slug in (".", ".."):
        return "run"
    return slug


# ---------------------------------------------------------------------------
# Path resolution
# ---------------------------------------------------------------------------


def resolve_cr_artifact_paths(
    *,
    run_label: str,
    config: CRArtifactConfig | None = None,
) -> CRArtifactPaths:
    """Resolve CR artifact paths for *run_label*.

    Layout::

        root_dir/
          archive/
            markdown/{safe_run_label}.md
            html/{safe_run_label}.html
          latest/
            cr_markdown.md
            cr.html

    Returns paths only — does NOT create directories.  All returned paths stay
    under ``config.root_dir`` because the sanitized label can never contain a
    path separator.
    """
    if config is None:
        config = CRArtifactConfig()

    root = Path(config.root_dir)
    safe = sanitize_artifact_label(run_label)

    markdown_archive_dir = root / config.markdown_archive_dirname
    html_archive_dir = root / config.html_archive_dirname
    latest_dir = root / config.latest_dirname

    return CRArtifactPaths(
        markdown_archive_path=markdown_archive_dir / f"{safe}.md",
        html_archive_path=html_archive_dir / f"{safe}.html",
        latest_markdown_path=latest_dir / config.markdown_filename,
        latest_html_path=latest_dir / config.html_filename,
    )


# ---------------------------------------------------------------------------
# Text writer
# ---------------------------------------------------------------------------


def write_text_artifact(
    path: Path | str,
    content: str,
    *,
    encoding: str = "utf-8",
) -> Path:
    """Write *content* to *path*, creating parent directories.

    Preserves *content* exactly (no newline translation).  Returns the written
    :class:`~pathlib.Path`.  Does NOT swallow exceptions, print, or log.
    """
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content, encoding=encoding, newline="")
    return p


# ---------------------------------------------------------------------------
# Bundle / single-format writers
# ---------------------------------------------------------------------------


def write_cr_artifact_bundle(
    *,
    markdown_text: str,
    html_text: str,
    run_label: str,
    config: CRArtifactConfig | None = None,
) -> CRArtifactPaths:
    """Write rendered Markdown + HTML to archive + latest artifact paths.

    Writes Markdown to ``markdown_archive_path`` and ``latest_markdown_path``,
    and HTML to ``html_archive_path`` and ``latest_html_path``.  Does NOT
    render anything, call scoring / decision / presentation, messaging
    delivery, or any existing archive / report system.
    """
    if config is None:
        config = CRArtifactConfig()

    paths = resolve_cr_artifact_paths(run_label=run_label, config=config)

    write_text_artifact(
        paths.markdown_archive_path, markdown_text, encoding=config.encoding
    )
    write_text_artifact(
        paths.latest_markdown_path, markdown_text, encoding=config.encoding
    )
    write_text_artifact(
        paths.html_archive_path, html_text, encoding=config.encoding
    )
    write_text_artifact(
        paths.latest_html_path, html_text, encoding=config.encoding
    )

    return paths


def write_cr_markdown_audit_artifact(
    markdown_text: str,
    *,
    run_label: str,
    config: CRArtifactConfig | None = None,
) -> CRArtifactPaths:
    """Write Markdown-only artifacts (archive markdown + latest markdown).

    The returned :class:`CRArtifactPaths` still contains all four resolved
    paths, but only the two Markdown files are written.
    """
    if config is None:
        config = CRArtifactConfig()

    paths = resolve_cr_artifact_paths(run_label=run_label, config=config)
    write_text_artifact(
        paths.markdown_archive_path, markdown_text, encoding=config.encoding
    )
    write_text_artifact(
        paths.latest_markdown_path, markdown_text, encoding=config.encoding
    )
    return paths


def write_cr_html_artifact(
    html_text: str,
    *,
    run_label: str,
    config: CRArtifactConfig | None = None,
) -> CRArtifactPaths:
    """Write HTML-only artifacts (archive HTML + latest HTML).

    The returned :class:`CRArtifactPaths` still contains all four resolved
    paths, but only the two HTML files are written.
    """
    if config is None:
        config = CRArtifactConfig()

    paths = resolve_cr_artifact_paths(run_label=run_label, config=config)
    write_text_artifact(
        paths.html_archive_path, html_text, encoding=config.encoding
    )
    write_text_artifact(
        paths.latest_html_path, html_text, encoding=config.encoding
    )
    return paths


# ---------------------------------------------------------------------------
# Combined render + write helper (PR9i / Part D)
# ---------------------------------------------------------------------------


def render_and_write_cr_artifacts(
    candidates: list[CRPresentedCandidate],
    *,
    run_label: str,
    markdown_config: CRMarkdownRenderConfig | None = None,
    html_config: CRHTMLRenderConfig | None = None,
    artifact_config: CRArtifactConfig | None = None,
    urgent_threshold: float = 80.0,
) -> CRArtifactPaths:
    """Render Markdown + HTML audits and write both via the artifact writer.

    Convenience wrapper around :func:`render_cr_markdown_audit`,
    :func:`render_cr_html_audit`, and :func:`write_cr_artifact_bundle`.  Not
    runtime integration — only writes through the explicit artifact writer.
    """
    markdown_text = render_cr_markdown_audit(
        candidates,
        run_label=run_label,
        config=markdown_config,
        urgent_threshold=urgent_threshold,
    )
    html_text = render_cr_html_audit(
        candidates,
        run_label=run_label,
        config=html_config,
        urgent_threshold=urgent_threshold,
    )
    return write_cr_artifact_bundle(
        markdown_text=markdown_text,
        html_text=html_text,
        run_label=run_label,
        config=artifact_config,
    )
