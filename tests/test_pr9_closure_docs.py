# coding=utf-8
"""
Lightweight checks for the PR9 CR-A MVP closure document.

These tests assert stable safety and handoff phrases only. They do not import
runtime modules and do not perform network I/O.
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent.parent
DOC_PATH = PROJECT_ROOT / "docs" / "pr9_cr_a_mvp_closure.md"

REAL_LOOKING_TELEGRAM_TOKEN = re.compile(r"\b\d{6,}:[A-Za-z0-9_-]{30,}\b")


def _doc_text() -> str:
    return DOC_PATH.read_text(encoding="utf-8")


class TestPR9ClosureDocs(unittest.TestCase):
    def test_doc_file_exists(self) -> None:
        self.assertTrue(DOC_PATH.exists())

    def test_required_phrases_appear(self) -> None:
        text = _doc_text()
        for phrase in (
            "PR9 is complete",
            "PTILOPSIS_CR_DRY_RUN",
            "PTILOPSIS_CR_TELEGRAM_SEND",
            "PR10",
            "dedupe",
            "cooldown",
            "alert-state",
            "Default behavior remains no-send",
        ):
            self.assertIn(phrase, text)

    def test_doc_contains_no_real_looking_telegram_token(self) -> None:
        self.assertIsNone(REAL_LOOKING_TELEGRAM_TOKEN.search(_doc_text()))


if __name__ == "__main__":
    unittest.main()
