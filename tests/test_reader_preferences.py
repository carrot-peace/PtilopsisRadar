import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from trendradar.content_policy import is_reader_noise, is_excluded_reader_item
from trendradar.esports import esports_item
from trendradar.reader_preferences import exclude_esports
from trendradar.cr.dispatch_plan import build_cr_a_dispatch_plan
from trendradar.cr.pipeline import CRPipelineConfig, build_cr_pipeline_from_primitives
from trendradar.cr.models import CRSourceItem, CRPrimitiveRecord


class ReaderPreferencesTests(unittest.TestCase):
    def test_preference_reload_and_disabled_public_interest_behavior(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "preferences.json"
            with patch.dict(os.environ, {"READER_PREFERENCES_PATH": str(path)}):
                self.assertFalse(exclude_esports())
                path.write_text(json.dumps({"exclude_esports": True}))
                self.assertTrue(is_reader_noise("电竞场馆发生火灾，警方通报"))
                self.assertTrue(is_reader_noise("高热未归类·消息", ["EDG官宣选手离队"]))
                self.assertFalse(is_reader_noise("上海本地兜底", ["EDG官宣选手离队"]))
                path.write_text(json.dumps({"exclude_esports": False}) + "\n")
                self.assertFalse(is_reader_noise("电竞场馆发生火灾，警方通报"))

    def test_ambiguous_names_and_non_esports_are_retained(self):
        for title in (
            "MSI公司发布显卡", "三星S16手机发布", "Intel 14th Gen处理器",
            "救援人员时薪1欧,车手麻了", "上海地铁停运", "中国男篮vs日本男篮",
            "TEST测试", "WE ARE READY", "AL公司裁员", "HYROX选手赛场失禁",
            "Nobody knows the answer", "The Dark Knight票房创新高",
            "Grand Canyon国家公园开放", "NRG公司发布财报", "LOUD发布新专辑",
            "Atlanta Falcons球员转会", "Viper显卡发布", "Elk种群保护计划",
        ):
            with self.subTest(title=title):
                self.assertFalse(esports_item(title))

    def test_all_esports_including_incidents_and_secondary_titles(self):
        for title in (
            "BLG Knight 开播", "2026KPL年度总决赛正式开赛", "S赛怀旧金曲云南山歌版",
            "AL夺冠", "MSI比赛中选手送医", "EDG发文道歉", "CS2战队遭抢劫",
            "服务器爆炸,滔搏IG或重赛", "优势局翻车,IG葬送天胡开局",
        ):
            with self.subTest(title=title):
                self.assertTrue(esports_item(title))
        self.assertTrue(esports_item("现场情况通报", ["KPL比赛中断"]))

    def test_keyword_and_top_five_catch_all_cannot_bypass_preference(self):
        from trendradar.core.analyzer import count_word_frequency, count_rss_frequency
        groups = [{"group_key": "上海", "required": [], "normal": ["上海"]}]
        results = {"bilibili-hot-search": {
            title: {"ranks": [1], "url": "https://example.com/" + str(i)}
            for i, title in enumerate(("上海EDG.M赛程", "BLG Knight 开播", "上海道路停车新政"))
        }}
        stats, _ = count_word_frequency(results, groups, [], {}, mode="current", quiet=True,
                                       catch_all_enabled=True)
        self.assertEqual([t["title"] for g in stats for t in g["titles"]], ["上海道路停车新政"])
        self.assertEqual(len(results["bilibili-hot-search"]), 3)
        rss, _ = count_rss_frequency([
            {"title": "上海电竞场馆火灾", "url": "https://example.com/1"},
            {"title": "上海道路停车新政", "url": "https://example.com/2"},
        ], groups, [], quiet=True)
        self.assertEqual([t["title"] for g in rss for t in g["titles"]], ["上海道路停车新政"])

    def test_daily_exclusion_is_absent_from_body_noise_examples_and_appendix(self):
        from types import SimpleNamespace
        from trendradar.report.daily_v2 import build_daily_report_v2
        ai = SimpleNamespace(
            report_style="environment", success=True, overview="近期动态", overview_stats={},
            high_heat_unverified=[{"topic": "电竞场馆发生火灾，警方通报"}],
        )
        model = build_daily_report_v2(ai, {"stats": [{"word": "上海", "count": 2, "titles": [
            {"title": "上海EDG.M赛程"}, {"title": "上海道路停车新政"},
        ]}]})
        self.assertEqual(model.main_items, [])
        self.assertEqual(model.suppressed_count, 0)
        self.assertEqual(model.raw_appendix.groups[0]["titles"], [{"title": "上海道路停车新政"}])
        self.assertEqual(model.raw_appendix.groups[0]["count"], 1)

    def test_specific_events_check_sources_but_mixed_keyword_groups_keep_other_news(self):
        from types import SimpleNamespace
        from trendradar.report.daily_v2 import build_daily_report_v2
        evidence = {"sample_titles": [{"title": "KPL比赛中断"}, {"title": "上海道路停车新政"}],
                    "source_links": [{"title": "KPL比赛中断", "url": "https://example.com/esports"},
                                     {"title": "上海道路停车新政", "url": "https://example.com/roads"}]}
        self.assertTrue(is_excluded_reader_item("现场情况通报", [{"title": "KPL比赛中断"}]))
        self.assertTrue(is_reader_noise("现场情况通报", [{"title": "KPL比赛中断"}]))
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "keywords.txt"
            path.write_text("[WORD_GROUPS]\n\n[城市线索]\n上海\n")
            with patch.dict(os.environ, {"FREQUENCY_WORDS_PATH": str(path)}):
                self.assertFalse(is_excluded_reader_item("城市线索", evidence["sample_titles"]))
                ai = SimpleNamespace(report_style="environment", success=True, overview="近期动态",
                                     overview_stats={}, high_heat_unverified=[
                                         {"topic": "城市线索", "evidence_detail": evidence}])
                model = build_daily_report_v2(ai, {"stats": []})
                self.assertEqual([i.topic for i in model.main_items], ["城市线索"])
                self.assertEqual([i["title"] for i in model.main_items[0].samples], ["上海道路停车新政"])
                self.assertEqual([i["title"] for i in model.main_items[0].source_links], ["上海道路停车新政"])
        self.assertEqual(len(evidence["sample_titles"]), 2)

    def test_folded_titles_and_counts_match_on_all_report_surfaces(self):
        from datetime import datetime
        from types import SimpleNamespace
        from trendradar.report.daily_v2 import build_daily_report_v2
        from trendradar.report.dashboard import render_current_dashboard_html, _event_radar
        from trendradar.dr.formatter import _deterministic_brief
        ai = SimpleNamespace(
            report_style="environment", success=True, overview="近期动态",
            overview_stats={"label_counts": {"sentiment_heavy": 2}, "background_count": 2},
            high_heat_unverified=[{"topic": "电竞场馆发生火灾，警方通报"},
                                  {"topic": "某明星恋情"}, {"topic": "上海道路停车新政"}],
            sentiment_heavy=[{"topic": "BLG粉丝争议"}, {"topic": "社区投诉情绪聚集"}],
            background_notes=["EDG发文道歉", "道路建设背景"],
        )
        model = build_daily_report_v2(ai, {"stats": []})
        self.assertEqual(model.suppressed_count, 3)
        self.assertEqual(model.radar["suppressed"], 3)
        self.assertEqual(_event_radar(ai)["suppressed"], 3)
        self.assertIn("另有 3 个非重点项", _deterministic_brief(ai))
        html = render_current_dashboard_html(ai, {}, datetime(2026, 11, 16), "current",
            rss_items=[{"word": "上海", "count": 2, "titles": [
                {"title": "上海EDG.M赛程"}, {"title": "上海道路停车新政"}]}])
        for title in ("电竞场馆发生火灾，警方通报", "BLG粉丝争议", "EDG发文道歉", "上海EDG.M赛程"):
            self.assertNotIn(title, html)
        self.assertIn("已抑制 3", html)
        self.assertIn("上海道路停车新政", html)
        examples = [s for group in model.suppressed for s in group.examples]
        self.assertEqual(set(examples), {"某明星恋情", "社区投诉情绪聚集", "道路建设背景"})

    def test_appendix_removes_known_items_without_collapsing_a_capped_total(self):
        from trendradar.report.daily_v2 import _build_raw_appendix
        result = _build_raw_appendix([{"word": "上海", "count": 10, "titles": [
            {"title": "上海EDG.M赛程"}, {"title": "上海道路停车新政"}]}])
        self.assertEqual(result.groups[0]["count"], 9)

    def test_cr_urgent_exclusion_is_audited_but_never_creates_diagnostic_push(self):
        from dataclasses import replace
        # Three fresh top-ranked sources ensure the test crosses urgent.
        items = [CRSourceItem(
            title="BLG对阵GEN", source_type="hotlist", source_id=source,
            source_name=source, url="https://example.com/match",
            normalized_rank=1, current_rank=1, is_visible=True, is_new=True,
            is_new_semantics="new_titles_detection", observed_in_current_run=True,
        ) for source in ("weibo", "bilibili-hot-search", "douyin")]
        primitives = [CRPrimitiveRecord(source_items=items)]
        # A low explicit urgent threshold isolates preference priority from heat formulas.
        from trendradar.cr.decision import CRDecisionPolicy
        cfg = CRPipelineConfig(exclude_esports=True, decision=CRDecisionPolicy(urgent_threshold=1))
        filtered = build_cr_pipeline_from_primitives(primitives, run_label="test", config=cfg,
                                                     urgent_threshold=1)
        self.assertTrue(filtered.decisions)
        self.assertTrue(all(d.level == "suppress" for d in filtered.decisions))
        self.assertTrue(all(not d.bypasses_quiet for d in filtered.decisions))
        self.assertIn("reader_preference:exclude_esports", filtered.decisions[0].suppress_labels)
        self.assertEqual(filtered.high_score_suppressed_count, 0)
        self.assertFalse(build_cr_a_dispatch_plan(filtered).should_dispatch)
        restored = build_cr_pipeline_from_primitives(
            primitives, run_label="test", config=replace(cfg, exclude_esports=False), urgent_threshold=1)
        self.assertTrue(build_cr_a_dispatch_plan(restored).should_dispatch)


if __name__ == "__main__":
    unittest.main()
