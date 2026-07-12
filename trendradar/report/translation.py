# coding=utf-8
"""
Artifact/report translation helpers.

This module belongs to the Generation Plane.  It must not import notification
or transport code.
"""

from __future__ import annotations

import copy
from typing import Any, Dict, List, Optional, Protocol


class ArtifactTranslator(Protocol):
    """Structural interface for a report/artifact translator."""

    enabled: bool
    scope: Dict[str, Any]
    target_language: str

    def translate_batch(self, titles: List[str]) -> Any: ...


def translate_report_content(
    report_data: Dict[str, Any],
    rss_items: Optional[List[Dict[str, Any]]] = None,
    rss_new_items: Optional[List[Dict[str, Any]]] = None,
    translator: Optional[ArtifactTranslator] = None,
    display_regions: Optional[Dict[str, Any]] = None,
    skip_rss: bool = False,
    debug: bool = False,
) -> tuple[Dict[str, Any], Optional[List[Dict[str, Any]]], Optional[List[Dict[str, Any]]]]:
    """Translate report and RSS artifact content without touching Transport."""
    if not translator or not translator.enabled:
        return report_data, rss_items, rss_new_items

    print(f"[翻译] 开始翻译内容到 {translator.target_language}...")

    scope = translator.scope
    display_regions = display_regions or {}

    report_data = copy.deepcopy(report_data)
    rss_items = copy.deepcopy(rss_items) if rss_items else None
    rss_new_items = copy.deepcopy(rss_new_items) if rss_new_items else None

    titles_to_translate: list[str] = []
    title_locations: list[tuple[str, int, int]] = []

    if scope.get("HOTLIST", True) and display_regions.get("HOTLIST", True):
        for stat_idx, stat in enumerate(report_data.get("stats", [])):
            for title_idx, title_data in enumerate(stat.get("titles", [])):
                titles_to_translate.append(title_data.get("title", ""))
                title_locations.append(("stats", stat_idx, title_idx))

        for source_idx, source in enumerate(report_data.get("new_titles", [])):
            for title_idx, title_data in enumerate(source.get("titles", [])):
                titles_to_translate.append(title_data.get("title", ""))
                title_locations.append(("new_titles", source_idx, title_idx))

    if (
        not skip_rss
        and rss_items
        and scope.get("RSS", True)
        and display_regions.get("RSS", True)
    ):
        for stat_idx, stat in enumerate(rss_items):
            for title_idx, title_data in enumerate(stat.get("titles", [])):
                titles_to_translate.append(title_data.get("title", ""))
                title_locations.append(("rss_items", stat_idx, title_idx))

    if (
        not skip_rss
        and rss_new_items
        and scope.get("RSS", True)
        and display_regions.get("RSS", True)
        and display_regions.get("NEW_ITEMS", True)
    ):
        for stat_idx, stat in enumerate(rss_new_items):
            for title_idx, title_data in enumerate(stat.get("titles", [])):
                titles_to_translate.append(title_data.get("title", ""))
                title_locations.append(("rss_new_items", stat_idx, title_idx))

    if not titles_to_translate:
        print("[翻译] 没有需要翻译的内容")
        return report_data, rss_items, rss_new_items

    print(f"[翻译] 共 {len(titles_to_translate)} 条标题待翻译")

    result = translator.translate_batch(titles_to_translate)

    if result.success_count == 0:
        print(f"[翻译] 翻译失败: {result.results[0].error if result.results else '未知错误'}")
        return report_data, rss_items, rss_new_items

    print(f"[翻译] 翻译完成: {result.success_count}/{result.total_count} 成功")

    if debug:
        if result.prompt:
            print(f"[翻译][DEBUG] === 发送给 AI 的 Prompt ===")
            print(result.prompt)
            print(f"[翻译][DEBUG] === Prompt 结束 ===")
        if result.raw_response:
            print(f"[翻译][DEBUG] === AI 原始响应 ===")
            print(result.raw_response)
            print(f"[翻译][DEBUG] === 响应结束 ===")
        expected = len(titles_to_translate)
        if result.parsed_count != expected:
            print(f"[翻译][DEBUG] [警告] 行数不匹配：期望 {expected} 条，AI 返回 {result.parsed_count} 条")
        unchanged_count = 0
        for i, res in enumerate(result.results):
            if not res.success and res.error:
                print(f"[翻译][DEBUG] [{i+1}] !! 失败: {res.error}")
            elif res.original_text == res.translated_text:
                unchanged_count += 1
            else:
                print(f"[翻译][DEBUG] [{i+1}] {res.original_text} => {res.translated_text}")
        if unchanged_count > 0:
            print(f"[翻译][DEBUG] （另有 {unchanged_count} 条未变化，已省略）")

    for i, (loc_type, idx1, idx2) in enumerate(title_locations):
        if i >= len(result.results) or not result.results[i].success:
            continue
        translated = result.results[i].translated_text
        if not translated or not translated.strip():
            continue
        if loc_type == "stats":
            report_data["stats"][idx1]["titles"][idx2]["title"] = translated
        elif loc_type == "new_titles":
            report_data["new_titles"][idx1]["titles"][idx2]["title"] = translated
        elif loc_type == "rss_items" and rss_items:
            rss_items[idx1]["titles"][idx2]["title"] = translated
        elif loc_type == "rss_new_items" and rss_new_items:
            rss_new_items[idx1]["titles"][idx2]["title"] = translated

    return report_data, rss_items, rss_new_items
