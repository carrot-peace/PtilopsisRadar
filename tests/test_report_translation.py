# coding=utf-8
"""
Tests for generation-owned report/artifact translation.

No notification dispatchers, senders, CR sinks, or network calls are used here.
"""

from __future__ import annotations

import copy
import unittest
from types import SimpleNamespace

from trendradar.report.translation import translate_report_content


class FakeTranslator:
    def __init__(
        self,
        translated: list[str] | None = None,
        *,
        enabled: bool = True,
        scope: dict | None = None,
        failures: set[int] | None = None,
        empty_results: set[int] | None = None,
    ):
        self.enabled = enabled
        self.target_language = "English"
        self.scope = scope or {"HOTLIST": True, "RSS": True}
        self.translated = translated or []
        self.failures = failures or set()
        self.empty_results = empty_results or set()
        self.calls: list[list[str]] = []

    def translate_batch(self, texts: list[str]):
        self.calls.append(list(texts))
        results = []
        success_count = 0
        for idx, text in enumerate(texts):
            if idx in self.failures:
                results.append(
                    SimpleNamespace(
                        success=False,
                        original_text=text,
                        translated_text="",
                        error="boom",
                    )
                )
                continue
            translated = "" if idx in self.empty_results else self.translated[idx]
            success_count += 1
            results.append(
                SimpleNamespace(
                    success=True,
                    original_text=text,
                    translated_text=translated,
                    error="",
                )
            )
        return SimpleNamespace(
            results=results,
            success_count=success_count,
            fail_count=len(texts) - success_count,
            total_count=len(texts),
            prompt="",
            raw_response="",
            parsed_count=len(texts),
        )


def _report_data():
    return {
        "stats": [
            {"titles": [{"title": "hot title"}]},
        ],
        "new_titles": [
            {"titles": [{"title": "new hot title"}]},
        ],
    }


def _rss_items():
    return [
        {"titles": [{"title": "rss title"}]},
    ]


def _rss_new_items():
    return [
        {"titles": [{"title": "rss new title"}]},
    ]


class TestReportTranslation(unittest.TestCase):
    def test_translator_none_passthrough_returns_original_objects(self) -> None:
        report = _report_data()
        rss = _rss_items()
        rss_new = _rss_new_items()

        translated = translate_report_content(report, rss, rss_new, translator=None)

        self.assertEqual((report, rss, rss_new), translated)
        self.assertIs(translated[0], report)
        self.assertIs(translated[1], rss)
        self.assertIs(translated[2], rss_new)

    def test_disabled_translator_passthrough_returns_original_objects(self) -> None:
        report = _report_data()
        rss = _rss_items()
        rss_new = _rss_new_items()
        translator = FakeTranslator(enabled=False)

        translated = translate_report_content(report, rss, rss_new, translator=translator)

        self.assertEqual((report, rss, rss_new), translated)
        self.assertEqual([], translator.calls)

    def test_report_rss_and_rss_new_titles_translate_in_order(self) -> None:
        translator = FakeTranslator(["HOT", "NEW", "RSS", "RSSNEW"])

        report, rss, rss_new = translate_report_content(
            _report_data(),
            _rss_items(),
            _rss_new_items(),
            translator=translator,
            display_regions={"HOTLIST": True, "RSS": True, "NEW_ITEMS": True},
        )

        self.assertEqual([["hot title", "new hot title", "rss title", "rss new title"]], translator.calls)
        self.assertEqual("HOT", report["stats"][0]["titles"][0]["title"])
        self.assertEqual("NEW", report["new_titles"][0]["titles"][0]["title"])
        self.assertEqual("RSS", rss[0]["titles"][0]["title"])
        self.assertEqual("RSSNEW", rss_new[0]["titles"][0]["title"])

    def test_display_regions_control_hotlist_and_rss_translation(self) -> None:
        translator = FakeTranslator(["RSS"])

        report, rss, rss_new = translate_report_content(
            _report_data(),
            _rss_items(),
            _rss_new_items(),
            translator=translator,
            display_regions={"HOTLIST": False, "RSS": True, "NEW_ITEMS": False},
        )

        self.assertEqual([["rss title"]], translator.calls)
        self.assertEqual("hot title", report["stats"][0]["titles"][0]["title"])
        self.assertEqual("new hot title", report["new_titles"][0]["titles"][0]["title"])
        self.assertEqual("RSS", rss[0]["titles"][0]["title"])
        self.assertEqual("rss new title", rss_new[0]["titles"][0]["title"])

    def test_skip_rss_translates_only_report_data(self) -> None:
        translator = FakeTranslator(["HOT", "NEW"])

        report, rss, rss_new = translate_report_content(
            _report_data(),
            _rss_items(),
            _rss_new_items(),
            translator=translator,
            display_regions={"HOTLIST": True, "RSS": True, "NEW_ITEMS": True},
            skip_rss=True,
        )

        self.assertEqual([["hot title", "new hot title"]], translator.calls)
        self.assertEqual("HOT", report["stats"][0]["titles"][0]["title"])
        self.assertEqual("NEW", report["new_titles"][0]["titles"][0]["title"])
        self.assertEqual("rss title", rss[0]["titles"][0]["title"])
        self.assertEqual("rss new title", rss_new[0]["titles"][0]["title"])

    def test_partial_failure_and_empty_translation_preserve_original_values(self) -> None:
        translator = FakeTranslator(
            ["HOT", "NEW", "RSS", ""],
            failures={1},
            empty_results={3},
        )

        report, rss, rss_new = translate_report_content(
            _report_data(),
            _rss_items(),
            _rss_new_items(),
            translator=translator,
            display_regions={"HOTLIST": True, "RSS": True, "NEW_ITEMS": True},
        )

        self.assertEqual("HOT", report["stats"][0]["titles"][0]["title"])
        self.assertEqual("new hot title", report["new_titles"][0]["titles"][0]["title"])
        self.assertEqual("RSS", rss[0]["titles"][0]["title"])
        self.assertEqual("rss new title", rss_new[0]["titles"][0]["title"])

    def test_translation_does_not_mutate_inputs(self) -> None:
        report = _report_data()
        rss = _rss_items()
        rss_new = _rss_new_items()
        original = copy.deepcopy((report, rss, rss_new))
        translator = FakeTranslator(["HOT", "NEW", "RSS", "RSSNEW"])

        translated = translate_report_content(
            report,
            rss,
            rss_new,
            translator=translator,
            display_regions={"HOTLIST": True, "RSS": True, "NEW_ITEMS": True},
        )

        self.assertEqual(original, (report, rss, rss_new))
        self.assertIsNot(translated[0], report)
        self.assertIsNot(translated[1], rss)
        self.assertIsNot(translated[2], rss_new)


if __name__ == "__main__":
    unittest.main()
