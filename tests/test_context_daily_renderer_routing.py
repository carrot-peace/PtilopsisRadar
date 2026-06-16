# coding=utf-8
"""
AppContext.render_html() 的 renderer routing 测试。

验证 PR-D1：
  - daily artifact route 使用 Daily Report v2 renderer；
  - current / incremental 仍走 existing newsletter renderer；
  - AppContext.generate_html 保留 daily artifact path contract。

测试方式（不经 __main__ / 端到端）：
  - 用 _bootstrap 注册真实 trendradar.ai.* 依赖；
  - 加载真实 trendradar.report.daily_v2 / newsletter；
  - 把 context.py 的其余重依赖（utils.time / core / storage 等）stub 成
    占位模块，使 context.py 能在精简解释器下加载；
  - 加载真实 trendradar.context，再用 spy 包裹 renderer，断言 daily / non-daily
    route 选择正确。

覆盖：
  1. daily + ai_analysis=None              → DR v2；含 no-AI notice
  2. daily + ai_analysis.success=False     → DR v2；含 no-AI notice
  3. daily + report_style!="environment"   → DR v2；含 no-AI notice
  4. daily + usable environment AI result  → DR v2；正常 overview
  5. daily + AI-backed missing overview    → DR v2 degraded notice
  6. generate_html(daily)                  → 写 existing daily paths
  7. non-daily + ai_analysis=None          → newsletter
  8. non-daily + usable environment AI     → newsletter
"""

import importlib.util
import os
import shutil
import sys
import tempfile
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
    # 真实 report pieces：context imports generator from the package and
    # renderers from submodules.
    report_pkg = _stub_pkg("trendradar.report")
    gen = _load_real("trendradar.report.generator", "trendradar/report/generator.py")
    report_pkg.prepare_report_data = gen.prepare_report_data
    report_pkg.generate_html_report = gen.generate_html_report
    _load_real("trendradar.report.dashboard", "trendradar/report/dashboard.py")
    _load_real("trendradar.report.daily_v2", "trendradar/report/daily_v2.py")
    _load_real("trendradar.report.newsletter", "trendradar/report/newsletter.py")

    # context.py 的其余 import 目标：纯 stub 即可（routing 不会真正调用）
    _stub_pkg("trendradar.utils")
    _stub_pkg("trendradar.utils.time")
    _stub_pkg("trendradar.core")  # _bootstrap 已建为普通模块，这里补 __getattr__
    _stub_pkg("trendradar.ai")  # 同上，补 __getattr__ 以解析 AITranslator
    _stub_pkg("trendradar.ai.filter")
    _stub_pkg("trendradar.storage")

    return _load_real("trendradar.context", "trendradar/context.py")


_CTX = _load_context_module()
AppContext = _CTX.AppContext
DV2 = sys.modules["trendradar.report.daily_v2"]


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


def _stats():
    return [
        {
            "word": "示例关键词",
            "count": 1,
            "titles": [
                _bootstrap.make_title(
                    "某条热榜标题",
                    "微博",
                    3,
                    time_display="09:30",
                    rank_threshold=50,
                )
            ],
        }
    ]


class _RoutingTestBase(unittest.TestCase):
    def setUp(self):
        # 用 spy 包裹两个 renderer：记录调用，并保留真实行为
        self.nl_calls = []
        self.dv2_calls = []

        real_nl = _CTX.render_newsletter_report
        real_dv2 = _CTX.render_daily_report_v2

        def nl_spy(*args, **kwargs):
            self.nl_calls.append((args, kwargs))
            return real_nl(*args, **kwargs)  # 真实 newsletter 输出（含/不含 fallback）

        def dv2_spy(*args, **kwargs):
            self.dv2_calls.append((args, kwargs))
            return real_dv2(*args, **kwargs)

        self._orig_nl = _CTX.render_newsletter_report
        self._orig_dv2 = _CTX.render_daily_report_v2
        _CTX.render_newsletter_report = nl_spy
        _CTX.render_daily_report_v2 = dv2_spy

        self.ctx = AppContext({})
        # newsletter 内部会 get_time_func().strftime(...)，给一个真实 datetime
        self.ctx.get_time = lambda: datetime(2026, 6, 5, 9, 0)

    def tearDown(self):
        _CTX.render_newsletter_report = self._orig_nl
        _CTX.render_daily_report_v2 = self._orig_dv2

    def _assert_newsletter_only(self, out):
        self.assertEqual(len(self.nl_calls), 1, "应调用 render_newsletter_report")
        self.assertEqual(len(self.dv2_calls), 0, "不应调用 render_daily_report_v2")
        self.assertIn("<!DOCTYPE html>", out)  # 真实 newsletter shell

    def _assert_daily_v2_only(self, out):
        self.assertEqual(len(self.dv2_calls), 1, "应调用 render_daily_report_v2")
        self.assertEqual(len(self.nl_calls), 0, "daily route 不应调用 render_newsletter_report")
        self.assertIn("<!DOCTYPE html>", out)
        self.assertIn("<h1>每日盘面 · v2</h1>", out)


class TestDailyUsesDailyReportV2(_RoutingTestBase):
    def test_daily_ai_none(self):
        out = self.ctx.render_html(_report_data(), 1, mode="daily", ai_analysis=None)
        self._assert_daily_v2_only(out)
        self.assertIn(FALLBACK_NOTICE, out)
        self.assertIn('<div class="no-ai-notice">', out)
        self.assertIn("某条热榜标题", out)  # 程序已采集内容照常展示

    def test_daily_ai_success_false(self):
        ai = AIAnalysisResult(success=False, report_style="environment")
        out = self.ctx.render_html(_report_data(), 1, mode="daily", ai_analysis=ai)
        self._assert_daily_v2_only(out)
        self.assertIn(FALLBACK_NOTICE, out)

    def test_daily_non_environment_style(self):
        ai = AIAnalysisResult(success=True, report_style="classic")
        out = self.ctx.render_html(_report_data(), 1, mode="daily", ai_analysis=ai)
        self._assert_daily_v2_only(out)
        self.assertIn(FALLBACK_NOTICE, out)

    def test_daily_usable_environment_result(self):
        ai = AIAnalysisResult(
            success=True, report_style="environment", overview="今日盘面平稳"
        )
        out = self.ctx.render_html(_report_data(), 1, mode="daily", ai_analysis=ai)
        self._assert_daily_v2_only(out)
        self.assertNotIn(FALLBACK_NOTICE, out)
        self.assertNotIn('<div class="no-ai-notice">', out)
        self.assertIn("今日盘面平稳", out)

    def test_daily_ai_backed_missing_overview_degrades(self):
        ai = AIAnalysisResult(success=True, report_style="environment", overview="")
        out = self.ctx.render_html(_report_data(), 1, mode="daily", ai_analysis=ai)
        self._assert_daily_v2_only(out)
        self.assertIn(DV2.DEGRADED_OVERVIEW_NOTICE, out)
        self.assertIn('<div class="degraded-notice">', out)

    def test_generate_html_preserves_daily_artifact_paths(self):
        tmp = tempfile.mkdtemp()
        self.addCleanup(lambda: shutil.rmtree(tmp, ignore_errors=True))
        prev = os.getcwd()
        os.chdir(tmp)
        self.addCleanup(lambda: os.chdir(prev))
        self.ctx.format_date = lambda: "2026-06-05"
        self.ctx.format_time = lambda: "09-00"

        ai = AIAnalysisResult(
            success=True, report_style="environment", overview="日报路径总览"
        )
        html_file = self.ctx.generate_html(
            _stats(),
            1,
            mode="daily",
            ai_analysis=ai,
        )

        self.assertEqual(html_file, os.path.join("output", "html", "2026-06-05", "09-00.html"))
        paths = [
            html_file,
            os.path.join("output", "html", "latest", "daily.html"),
            os.path.join("output", "public", "daily", "full.html"),
        ]
        for path in paths:
            self.assertTrue(os.path.exists(path), path)
            with open(path, encoding="utf-8") as f:
                content = f.read()
            self.assertIn("<h1>每日盘面 · v2</h1>", content)
            self.assertIn("日报路径总览", content)
        self.assertFalse(os.path.exists(os.path.join("output", "public", "current", "full.html")))


class TestNonDailyAllNewsletter(_RoutingTestBase):
    def test_non_daily_ai_none_uses_newsletter(self):
        """PR7e: non-daily + 无 AI → 统一走 newsletter（不再回落 classic HTML）。"""
        out = self.ctx.render_html(_report_data(), 1, mode="current", ai_analysis=None)
        self._assert_newsletter_only(out)
        self.assertIn(FALLBACK_NOTICE, out)

    def test_non_daily_usable_environment_still_newsletter(self):
        ai = AIAnalysisResult(
            success=True, report_style="environment", overview="当前盘面"
        )
        out = self.ctx.render_html(_report_data(), 1, mode="current", ai_analysis=ai)
        self._assert_newsletter_only(out)
        self.assertNotIn(FALLBACK_NOTICE, out)


if __name__ == "__main__":
    unittest.main()
