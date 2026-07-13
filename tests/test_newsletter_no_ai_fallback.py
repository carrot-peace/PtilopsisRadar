# coding=utf-8
"""
newsletter environment daily renderer 的 no-AI fallback 测试。

直接测试 render_newsletter_report()（不经 AppContext.render_html() 路由），覆盖：
  - ai_analysis is None
  - ai_analysis.success is False
  - ai_analysis.report_style != "environment"
  - empty stats / no RSS
  - 可用 environment AI result（fallback 文案不出现，正常输出保留）
并单测 _is_usable_environment_ai 判定。
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(__file__))
import _bootstrap  # noqa: E402

_BOOT = _bootstrap.load_all()  # 注册 trendradar.ai.* 依赖到 sys.modules
_bootstrap._ensure_pkg("trendradar.report")
NL = _bootstrap._load_file(
    "trendradar.report.newsletter", "trendradar/report/newsletter.py"
)
AIAnalysisResult = _BOOT.analyzer.AIAnalysisResult

FALLBACK_NOTICE = (
    "本轮 AI 分析不可用；本报告仅展示程序已采集内容和可用元数据，不生成额外结论。"
)


def _report_data(with_stats=True):
    if not with_stats:
        return {"stats": [], "failed_ids": []}
    return {
        "stats": [
            {
                "word": "示例关键词",
                "count": 1,
                "titles": [_bootstrap.make_title("某条热榜标题", "微博", 3)],
            }
        ],
        "failed_ids": [],
    }


def _render(report_data, ai_analysis):
    return NL.render_newsletter_report(
        report_data,
        total_titles=1,
        mode="daily",
        ai_analysis=ai_analysis,
    )


class TestUsableEnvironmentAiHelper(unittest.TestCase):
    def test_none_is_not_usable(self):
        self.assertFalse(NL._is_usable_environment_ai(None))

    def test_success_false_is_not_usable(self):
        r = AIAnalysisResult(success=False, report_style="environment")
        self.assertFalse(NL._is_usable_environment_ai(r))

    def test_unsupported_style_is_not_usable(self):
        r = AIAnalysisResult(success=True, report_style="unsupported")
        self.assertFalse(NL._is_usable_environment_ai(r))

    def test_proper_environment_result_is_usable(self):
        r = AIAnalysisResult(success=True, report_style="environment")
        self.assertTrue(NL._is_usable_environment_ai(r))


class TestNoAiFallback(unittest.TestCase):
    def _assert_shell(self, out):
        # daily/environment report 基础结构关键标记
        self.assertIn("<!DOCTYPE html>", out)
        self.assertIn("Ptilopsis Radar", out)
        self.assertIn("每日盘面", out)  # mode="daily" 的 mode_label
        self.assertIn("<footer>", out)

    def test_ai_analysis_none(self):
        out = _render(_report_data(), ai_analysis=None)
        self._assert_shell(out)
        self.assertIn(FALLBACK_NOTICE, out)
        self.assertIn('<div class="ai-unavailable">', out)
        # 仍展示程序已采集内容
        self.assertIn("某条热榜标题", out)

    def test_ai_success_false(self):
        r = AIAnalysisResult(success=False, report_style="environment")
        out = _render(_report_data(), ai_analysis=r)
        self._assert_shell(out)
        self.assertIn(FALLBACK_NOTICE, out)

    def test_ai_wrong_report_style(self):
        r = AIAnalysisResult(success=True, report_style="unsupported")
        out = _render(_report_data(), ai_analysis=r)
        self._assert_shell(out)
        self.assertIn(FALLBACK_NOTICE, out)

    def test_empty_stats_and_no_rss(self):
        out = _render(_report_data(with_stats=False), ai_analysis=None)
        # 不 crash，输出稳定 fallback shell
        self._assert_shell(out)
        self.assertIn(FALLBACK_NOTICE, out)
        # 无 stats / 无 RSS 时数据区整体省略，不应出现假造结论
        self.assertNotIn("跨层", out)
        self.assertNotIn("已核实", out)

    def test_usable_environment_result_no_fallback(self):
        r = AIAnalysisResult(
            success=True, report_style="environment", overview="今日盘面平稳"
        )
        out = _render(_report_data(), ai_analysis=r)
        self._assert_shell(out)
        self.assertNotIn(FALLBACK_NOTICE, out)
        self.assertNotIn('<div class="ai-unavailable">', out)
        self.assertIn("今日盘面平稳", out)


if __name__ == "__main__":
    unittest.main()
