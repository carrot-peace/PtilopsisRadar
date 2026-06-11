# coding=utf-8
"""
Lightweight checks for the PR10 Run-2 design input note.

These tests assert only stable phrases and token safety. They do not import
runtime modules and do not perform network I/O.
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent.parent
DOC_PATH = PROJECT_ROOT / "docs" / "pr10_design_input_run2.md"

REAL_LOOKING_TELEGRAM_TOKEN = re.compile(r"\b\d{6,}:[A-Za-z0-9_-]{30,}\b")


def _doc_text() -> str:
    return DOC_PATH.read_text(encoding="utf-8")


class TestPR10DesignInputDocs(unittest.TestCase):
    def test_doc_file_exists(self) -> None:
        self.assertTrue(DOC_PATH.exists())

    def test_required_phrases_appear(self) -> None:
        text = _doc_text()
        for phrase in (
            "candidate_id is not stable",
            "cluster_key is not stable",
            "normalized title",
            "watch -> watch -> urgent -> alert -> watch -> watch",
            "30–60 minute cooldown",
            "This document is design input, not implementation",
        ):
            self.assertIn(phrase, text)

    def test_doc_contains_no_real_looking_telegram_token(self) -> None:
        self.assertIsNone(REAL_LOOKING_TELEGRAM_TOKEN.search(_doc_text()))


if __name__ == "__main__":
    unittest.main()
