# coding=utf-8
"""
AppContext.render_html() 的 daily renderer routing 测试。

验证 PR3b：daily mode 一律走 environment newsletter 渲染器，AI 是否可用只决定
newsletter 内部显示正常 editorial 还是 no-AI fallback notice，不再让 daily report
因为缺少/不可用 AI result 回落 legacy render_html_content()。

测试方式（不经 __main__ / 端到端）：
  - 用 _bootstrap 注册真实 trendradar.ai.* 依赖；
  - 加载真实 trendradar.report.newsletter（这样 daily 输出里能断言真实 fallback 文案）；
  - 把 context.py 的其余重依赖（utils.time / core / notification / storage 等）stub 成
    占位模块，使 context.py 能在精简解释器下加载；
  - 加载真实 trendradar.context，再用 spy 包裹 render_newsletter_report /
    render_html_content，断言 routing 选择了哪个渲染器。

覆盖：
  1. daily + ai_analysis=None              → newsletter；不调 render_html_content；含 fallback notice
  2. daily + ai_analysis.success=False     → newsletter；不调 render_html_content；含 fallback notice
  3. daily + report_style!="environment"   → newsletter；不调 render_html_content；含 fallback notice
  4. daily + usable environment AI result  → newsletter；无 fallback notice；正常 editorial
  5. non-daily + ai_analysis=None          → 保持现状：调 render_html_content，不强转 newsletter
  6. non-daily + usable environment AI     → 保持现状：仍走 newsletter（非 daily 环境路由不变）
"""

import importlib.util
import os
import sys
import types
import unittest
from datetime import datetime

sys.path.insert(0, os.path.dirname(__file__))
import _bootstrap  # noqa: E402

ROOT = _bootstrap.ROOT

_BOOT = _bootstrap.load_all()  # 注册真实 trendradar.ai.*（newsletter 依赖 ai.evidence）
AIAnalysisResult = _BOOT.analyzer.AIAnalysisResult

FALLBACK_NOTICE = (
    "本轮 AI 分析不可用；本报告仅展示程序已采集内容和可用元数据，不生成额外结论。"
)


def _attach_getattr(mod):
    """让 stub 模块对任意名字返回占位类（兼容 `from mod import Name` 与注解/Optional[]）。"""

    def __getattr__(name):  # PEP 562 module-level __getattr__
        obj = type(name, (), {})  # 动态类：可用于注解、Optional[...]、默认值
        setattr(mod, name, obj)  # 缓存，保证多次访问身份一致
        return obj

    mod.__getattr__ = __getattr__
    return mod


def _stub_pkg(name):
    mod = sys.modules.get(name)
    if mod is None:
        mod = types.ModuleType(name)
        mod.__path__ = []
        sys.modules[name] = mod
    return _attach_getattr(mod)


def _load_real(name, relpath):
    spec = importlib.util.spec_from_file_location(name, os.path.join(ROOT, relpath))
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


def _load_context_module():
    """在 stub 掉重依赖后加载真实 trendradar.context，返回模块对象。"""
    # 真实 newsletter：daily 输出需断言真实 fallback 文案
    _stub_pkg("trendradar.report")
    _load_real("trendradar.report.newsletter", "trendradar/report/newsletter.py")
    _stub_pkg("trendradar.report.dashboard")

    # context.py 的其余 import 目标：纯 stub 即可（routing 不会真正调用）
    _stub_pkg("trendradar.utils")
    _stub_pkg("trendradar.utils.time")
    _stub_pkg("trendradar.core")  # _bootstrap 已建为普通模块，这里补 __getattr__
    _stub_pkg("trendradar.notification")
    _stub_pkg("trendradar.ai")  # 同上，补 __getattr__ 以解析 AITranslator
    _stub_pkg("trendradar.ai.filter")
    _stub_pkg("trendradar.storage")

    return _load_real("trendradar.context", "trendradar/context.py")


_CTX = _load_context_module()
AppContext = _CTX.AppContext


def _report_data():
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


class _RoutingTestBase(unittest.TestCase):
    def setUp(self):
        # 用 spy 包裹两个渲染器：记录调用，并保留真实行为/可识别 sentinel
        self.nl_calls = []
        self.hc_calls = []

        real_nl = _CTX.render_newsletter_report

        def nl_spy(*args, **kwargs):
            self.nl_calls.append((args, kwargs))
            return real_nl(*args, **kwargs)  # 真实 newsletter 输出（含/不含 fallback）

        def hc_spy(*args, **kwargs):
            self.hc_calls.append((args, kwargs))
            return "LEGACY_HTML_CONTENT"

        self._orig_nl = _CTX.render_newsletter_report
        self._orig_hc = _CTX.render_html_content
        _CTX.render_newsletter_report = nl_spy
        _CTX.render_html_content = hc_spy

        self.ctx = AppContext({})
        # newsletter 内部会 get_time_func().strftime(...)，给一个真实 datetime
        self.ctx.get_time = lambda: datetime(2026, 6, 5, 9, 0)

    def tearDown(self):
        _CTX.render_newsletter_report = self._orig_nl
        _CTX.render_html_content = self._orig_hc

    def _assert_newsletter_only(self, out):
        self.assertEqual(len(self.nl_calls), 1, "应调用 render_newsletter_report")
        self.assertEqual(len(self.hc_calls), 0, "不应调用 render_html_content")
        self.assertIn("<!DOCTYPE html>", out)  # 真实 newsletter shell
        self.assertNotEqual(out, "LEGACY_HTML_CONTENT")


class TestDailyAlwaysNewsletter(_RoutingTestBase):
    def test_daily_ai_none(self):
        out = self.ctx.render_html(_report_data(), 1, mode="daily", ai_analysis=None)
        self._assert_newsletter_only(out)
        self.assertIn(FALLBACK_NOTICE, out)
        self.assertIn('<div class="ai-unavailable">', out)
        self.assertIn("某条热榜标题", out)  # 程序已采集内容照常展示

    def test_daily_ai_success_false(self):
        ai = AIAnalysisResult(success=False, report_style="environment")
        out = self.ctx.render_html(_report_data(), 1, mode="daily", ai_analysis=ai)
        self._assert_newsletter_only(out)
        self.assertIn(FALLBACK_NOTICE, out)

    def test_daily_non_environment_style(self):
        ai = AIAnalysisResult(success=True, report_style="classic")
        out = self.ctx.render_html(_report_data(), 1, mode="daily", ai_analysis=ai)
        self._assert_newsletter_only(out)
        self.assertIn(FALLBACK_NOTICE, out)

    def test_daily_usable_environment_result(self):
        ai = AIAnalysisResult(
            success=True, report_style="environment", overview="今日盘面平稳"
        )
        out = self.ctx.render_html(_report_data(), 1, mode="daily", ai_analysis=ai)
        self._assert_newsletter_only(out)
        self.assertNotIn(FALLBACK_NOTICE, out)
        self.assertNotIn('<div class="ai-unavailable">', out)
        self.assertIn("今日盘面平稳", out)


class TestNonDailyUnchanged(_RoutingTestBase):
    def test_non_daily_ai_none_keeps_legacy(self):
        # 现状：非 daily + 无 AI → 回落 render_html_content；本 PR 不扩大改动
        out = self.ctx.render_html(_report_data(), 1, mode="current", ai_analysis=None)
        self.assertEqual(len(self.hc_calls), 1, "non-daily 无 AI 仍应调用 render_html_content")
        self.assertEqual(len(self.nl_calls), 0, "non-daily 无 AI 不应强转 newsletter")
        self.assertEqual(out, "LEGACY_HTML_CONTENT")

    def test_non_daily_usable_environment_still_newsletter(self):
        # 现状：非 daily + 可用 environment AI → 仍走 newsletter（环境路由未变）
        ai = AIAnalysisResult(
            success=True, report_style="environment", overview="当前盘面"
        )
        out = self.ctx.render_html(_report_data(), 1, mode="current", ai_analysis=ai)
        self.assertEqual(len(self.nl_calls), 1)
        self.assertEqual(len(self.hc_calls), 0)
        self.assertNotEqual(out, "LEGACY_HTML_CONTENT")


if __name__ == "__main__":
    unittest.main()
