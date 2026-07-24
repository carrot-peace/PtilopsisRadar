# coding=utf-8
"""
Lightweight checks for the CR Telegram operator guide.

These tests intentionally assert only stable safety tokens and documented
limitations. They do not import runtime modules and do not perform network I/O.
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent.parent
DOC_PATH = PROJECT_ROOT / "docs" / "cr_telegram_operator_guide.md"

ENV_VARS = (
    "PTILOPSIS_CR_DISPATCH_MODE",
    "PTILOPSIS_CR_DRY_RUN",
    "PTILOPSIS_CR_TELEGRAM_SEND",
    "TELEGRAM_BOT_TOKEN",
    "TELEGRAM_OWNER_CHAT_IDS",
    "TELEGRAM_API_BASE_URL",
    "TELEGRAM_TIMEOUT_SECONDS",
    "PTILOPSIS_CR_TELEGRAM_ATTACH_HTML",
    "PTILOPSIS_CR_TELEGRAM_PARSE_MODE",
    "PTILOPSIS_CR_TELEGRAM_DISABLE_WEB_PAGE_PREVIEW",
)

REAL_LOOKING_TELEGRAM_TOKEN = re.compile(r"\b\d{6,}:[A-Za-z0-9_-]{30,}\b")


def _doc_text() -> str:
    return DOC_PATH.read_text(encoding="utf-8")


class TestCROperatorDocs(unittest.TestCase):
    def test_doc_file_exists(self) -> None:
        self.assertTrue(DOC_PATH.exists())

    def test_gate_names_appear(self) -> None:
        text = _doc_text()
        self.assertIn("PTILOPSIS_CR_DRY_RUN", text)
        self.assertIn("PTILOPSIS_CR_TELEGRAM_SEND", text)

    def test_all_telegram_env_vars_appear(self) -> None:
        text = _doc_text()
        for name in ENV_VARS:
            self.assertIn(name, text)

    def test_doc_contains_no_real_looking_telegram_token(self) -> None:
        self.assertIsNone(REAL_LOOKING_TELEGRAM_TOKEN.search(_doc_text()))

    def test_key_safety_and_limitation_phrases_appear(self) -> None:
        text = _doc_text().lower()
        for phrase in (
            "default behavior sends nothing",
            "no failed-delivery replay queue",
            "no subscriber administration commands",
            "no config.yaml integration",
        ):
            self.assertIn(phrase, text)


if __name__ == "__main__":
    unittest.main()
