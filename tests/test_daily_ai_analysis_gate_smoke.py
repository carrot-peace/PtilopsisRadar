# coding=utf-8
"""
PR4a smoke / regression tests。

验证 __main__._run_analysis_pipeline → context.render_html →
daily_v2 / newsletter renderer 完整链路中 AI analysis gate 行为
（不触发真实 crawler / AI / Telegram）。

覆盖：
  1. daily + DISPLAY.REGIONS.AI_ANALYSIS=false + usable environment AI result
     → daily full report 仍使用真实 ai_result
     → 输出中包含 AI overview / environment editorial
     → 输出中不包含 PR3a no-AI fallback notice

  2. daily + DISPLAY.REGIONS.AI_ANALYSIS=false + ai_result=None
     → daily full report 仍生成（不 crash）
     → 输出中包含 PR3a no-AI fallback notice

  3. current / incremental + DISPLAY.REGIONS.AI_ANALYSIS=false + usable AI result
     → PR8a 起忽略 gate：dashboard 始终收到真实 ai_result

  4. Telegram daily attachment path 稳定性
     → daily_digest 附件路径指向 public/daily/full.html
     → 不发送真实 Telegram 请求，不访问网络

测试方式（subprocess 隔离）：
  每个测试在独立子进程中加载 stub + 真实模块，不污染当前进程 sys.modules。
"""

import os
import subprocess
import sys
import textwrap
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

FALLBACK_NOTICE = (
    "本轮 AI 分析不可用；本报告仅展示程序已采集内容和可用元数据，不生成额外结论。"
)


def _run_in_subprocess(code: str):
    """Run test code in an isolated subprocess."""
    result = subprocess.run(
        [sys.executable, "-c", textwrap.dedent(code)],
        capture_output=True,
        text=True,
        cwd=ROOT,
    )
    return result


_SUBPROCESS_PREAMBLE = f"""
import importlib.util
import os
import sys
import types
from datetime import datetime
from types import SimpleNamespace

sys.path.insert(0, os.path.join({ROOT!r}, "tests"))
import _bootstrap

ROOT = _bootstrap.ROOT
_BOOT = _bootstrap.load_all()
AIAnalysisResult = _BOOT.analyzer.AIAnalysisResult

FALLBACK_NOTICE = {FALLBACK_NOTICE!r}


def _attach_getattr(mod):
    def __getattr__(name):
        obj = type(name, (), {{}})
        setattr(mod, name, obj)
        return obj
    mod.__getattr__ = __getattr__
    return mod


def _stub_pkg(name, is_pkg=True):
    mod = sys.modules.get(name)
    if mod is None:
        mod = types.ModuleType(name)
        sys.modules[name] = mod
    if is_pkg and not hasattr(mod, "__path__"):
        mod.__path__ = []
    return _attach_getattr(mod)


def _load_real(name, relpath):
    spec = importlib.util.spec_from_file_location(name, os.path.join(ROOT, relpath))
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


# Load real context (needs real report generator/renderers)
report_pkg = _stub_pkg("trendradar.report")
_GEN = _load_real("trendradar.report.generator", "trendradar/report/generator.py")
report_pkg.prepare_report_data = _GEN.prepare_report_data
report_pkg.generate_html_report = _GEN.generate_html_report
_load_real("trendradar.report.dashboard", "trendradar/report/dashboard.py")
_load_real("trendradar.report.daily_v2", "trendradar/report/daily_v2.py")
_load_real("trendradar.report.newsletter", "trendradar/report/newsletter.py")
_stub_pkg("trendradar.utils")
_stub_pkg("trendradar.utils.time")
_stub_pkg("trendradar.core")
_stub_pkg("trendradar.ai")
_stub_pkg("trendradar.ai.filter")
_stub_pkg("trendradar.storage")

_CTX = _load_real("trendradar.context", "trendradar/context.py")
AppContext = _CTX.AppContext

# Load real __main__ (needs additional stubs)
_stub_pkg("requests", is_pkg=False)
_stub_pkg("trendradar")
_stub_pkg("trendradar.context")
_stub_pkg("trendradar.core.analyzer")
_stub_pkg("trendradar.core.scheduler")
_stub_pkg("trendradar.core.cdn")
_stub_pkg("trendradar.crawler")

_MAIN = _load_real("trendradar.__main__", "trendradar/__main__.py")
NewsAnalyzer = _MAIN.NewsAnalyzer

_MODE_STRATEGY = {{
    "daily": {{"report_type": "全天汇总", "should_send_notification": False}},
    "current": {{"report_type": "当前榜单", "should_send_notification": False}},
    "incremental": {{"report_type": "增量分析", "should_send_notification": False}},
}}


def _report_data():
    return {{
        "stats": [
            {{
                "word": "示例关键词",
                "count": 1,
                "titles": [_bootstrap.make_title("某条热榜标题", "微博", 3)],
            }}
        ],
        "failed_ids": [],
    }}


def _make_ai_result(**overrides):
    defaults = dict(
        success=True,
        report_style="environment",
        overview="今日盘面平稳",
        overview_stats={{"anomaly": 2, "cross_layer": 1}},
        cross_layer_verified=[{{"title": "跨层信号", "sources": ["微博", "BBC"]}}],
    )
    defaults.update(overrides)
    return AIAnalysisResult(**defaults)


def _stats_with_titles():
    return [
        {{
            "word": "示例关键词",
            "count": 1,
            "titles": [_bootstrap.make_title("某条热榜标题", "微博", 3)],
        }}
    ], 1


def _make_ctx(*, ai_analysis_region=False, html_sink=None, dashboard_sink=None):
    return SimpleNamespace(
        config={{
            "AI_ANALYSIS": {{"ENABLED": True}},
            "STORAGE": {{"FORMATS": {{"HTML": True}}}},
            "DISPLAY": {{"REGIONS": {{"AI_ANALYSIS": ai_analysis_region}}}},
            "SHOW_VERSION_UPDATE": False,
        }},
        display_mode="keyword",
        platform_ids=["weibo"],
        count_frequency=lambda *a, **k: _stats_with_titles(),
        generate_html=lambda *a, **k: (html_sink.append(k) or "HTML_OUT") if html_sink is not None else "HTML_OUT",
        generate_dashboard=lambda *a, **k: dashboard_sink.append(k) if dashboard_sink is not None else None,
    )


def _make_fake(ctx, *, ai_result, mode="daily"):
    strategy = _MODE_STRATEGY[mode]
    return SimpleNamespace(
        filter_method="keyword",
        frequency_file=None,
        update_info=None,
        ctx=ctx,
        _hotlist_total_count=0,
        _rss_matched_count=0,
        _rss_total_count=0,
        _rss_source_total=0,
        _rss_source_failed=0,
        _get_mode_strategy=lambda: strategy,
        _run_ai_analysis=lambda *a, **k: ai_result,
    )


def _run_pipeline(fake, mode="daily"):
    return NewsAnalyzer._run_analysis_pipeline(
        fake,
        data_source={{"weibo": {{}}}},
        mode=mode,
        title_info={{}},
        new_titles={{}},
        word_groups=[],
        filter_words=[],
        id_to_name={{"weibo": "微博"}},
    )
"""


class TestDailyGateSmoke(unittest.TestCase):
    """PR4a: daily full report 在 AI_ANALYSIS=false 时仍使用真实 ai_result。"""

    def test_pipeline_daily_gate_false_passes_real_ai(self):
        code = _SUBPROCESS_PREAMBLE + """
ai = _make_ai_result(overview="跨层共振信号持续升温")
html_calls = []
dashboard_calls = []
ctx = _make_ctx(ai_analysis_region=False, html_sink=html_calls, dashboard_sink=dashboard_calls)
fake = _make_fake(ctx, ai_result=ai, mode="daily")
_run_pipeline(fake, "daily")
assert len(html_calls) == 1, "应调用 generate_html"
assert len(dashboard_calls) == 0, "不应调用 generate_dashboard"
assert html_calls[0].get("ai_analysis") is ai, "ai_analysis 应为原始 ai_result"
"""
        result = _run_in_subprocess(code)
        self.assertEqual(
            result.returncode, 0,
            f"Subprocess failed:\nstdout: {result.stdout}\nstderr: {result.stderr}"
        )

    def test_pipeline_daily_gate_false_none_ai_passes_none(self):
        code = _SUBPROCESS_PREAMBLE + """
html_calls = []
ctx = _make_ctx(ai_analysis_region=False, html_sink=html_calls)
fake = _make_fake(ctx, ai_result=None, mode="daily")
_run_pipeline(fake, "daily")
assert len(html_calls) == 1
assert html_calls[0].get("ai_analysis") is None
"""
        result = _run_in_subprocess(code)
        self.assertEqual(
            result.returncode, 0,
            f"Subprocess failed:\nstdout: {result.stdout}\nstderr: {result.stderr}"
        )

    def test_html_daily_gate_false_with_usable_ai_contains_editorial(self):
        code = _SUBPROCESS_PREAMBLE + """
ai = _make_ai_result(overview="跨层共振信号持续升温")
ctx = AppContext({"DISPLAY": {"REGIONS": {"AI_ANALYSIS": False}}})
ctx.get_time = lambda: datetime(2026, 6, 5, 9, 0)
out = ctx.render_html(_report_data(), 1, mode="daily", ai_analysis=ai)
assert "<!DOCTYPE html>" in out
assert "跨层共振信号持续升温" in out
assert FALLBACK_NOTICE not in out
assert '<div class="ai-unavailable">' not in out
assert '<div class="no-ai-notice">' not in out
assert "某条热榜标题" in out
"""
        result = _run_in_subprocess(code)
        self.assertEqual(
            result.returncode, 0,
            f"Subprocess failed:\nstdout: {result.stdout}\nstderr: {result.stderr}"
        )

    def test_html_daily_gate_false_with_none_ai_contains_fallback(self):
        code = _SUBPROCESS_PREAMBLE + """
ctx = AppContext({"DISPLAY": {"REGIONS": {"AI_ANALYSIS": False}}})
ctx.get_time = lambda: datetime(2026, 6, 5, 9, 0)
out = ctx.render_html(_report_data(), 1, mode="daily", ai_analysis=None)
assert "<!DOCTYPE html>" in out
assert FALLBACK_NOTICE in out
assert '<div class="no-ai-notice">' in out
assert "某条热榜标题" in out
"""
        result = _run_in_subprocess(code)
        self.assertEqual(
            result.returncode, 0,
            f"Subprocess failed:\nstdout: {result.stdout}\nstderr: {result.stderr}"
        )


class TestNonDailyGateUpdatedSmoke(unittest.TestCase):
    """PR8a: current / incremental 不再受 AI_ANALYSIS gate 影响。"""

    def test_current_gate_false_dashboard_gets_real_ai(self):
        code = _SUBPROCESS_PREAMBLE + """
ai = _make_ai_result()
dashboard_calls = []
ctx = _make_ctx(ai_analysis_region=False, dashboard_sink=dashboard_calls)
fake = _make_fake(ctx, ai_result=ai, mode="current")
_run_pipeline(fake, "current")
assert len(dashboard_calls) == 1
assert dashboard_calls[0].get("ai_analysis") is ai
"""
        result = _run_in_subprocess(code)
        self.assertEqual(
            result.returncode, 0,
            f"Subprocess failed:\nstdout: {result.stdout}\nstderr: {result.stderr}"
        )

    def test_incremental_gate_false_dashboard_gets_real_ai(self):
        code = _SUBPROCESS_PREAMBLE + """
ai = _make_ai_result()
dashboard_calls = []
ctx = _make_ctx(ai_analysis_region=False, dashboard_sink=dashboard_calls)
fake = _make_fake(ctx, ai_result=ai, mode="incremental")
_run_pipeline(fake, "incremental")
assert len(dashboard_calls) == 1
assert dashboard_calls[0].get("ai_analysis") is ai
"""
        result = _run_in_subprocess(code)
        self.assertEqual(
            result.returncode, 0,
            f"Subprocess failed:\nstdout: {result.stdout}\nstderr: {result.stderr}"
        )


class TestLegacyNotificationPackageDeleted(unittest.TestCase):
    """Legacy notification attachment helpers are deleted after PR-C2."""

    def test_daily_digest_attachment_path_helper_is_deleted(self):
        code = _SUBPROCESS_PREAMBLE + """
path = os.path.join(ROOT, "trendradar", "notification", "senders.py")
if os.path.exists(path):
    raise AssertionError("legacy attachment helper module still exists")
"""
        result = _run_in_subprocess(code)
        self.assertEqual(
            result.returncode, 0,
            f"Subprocess failed:\nstdout: {result.stdout}\nstderr: {result.stderr}"
        )

    def test_notification_package_import_is_unavailable(self):
        code = _SUBPROCESS_PREAMBLE + """
try:
    __import__("trendradar.notification")
except ModuleNotFoundError:
    pass
else:
    raise AssertionError("legacy notification package import unexpectedly succeeded")
"""
        result = _run_in_subprocess(code)
        self.assertEqual(
            result.returncode, 0,
            f"Subprocess failed:\nstdout: {result.stdout}\nstderr: {result.stderr}"
        )

    def test_daily_pipeline_does_not_stub_notification_package(self):
        code = _SUBPROCESS_PREAMBLE + """
if "trendradar.notification" in sys.modules:
    raise AssertionError("daily smoke preamble should not load notification")
"""
        result = _run_in_subprocess(code)
        self.assertEqual(
            result.returncode, 0,
            f"Subprocess failed:\nstdout: {result.stdout}\nstderr: {result.stderr}"
        )


if __name__ == "__main__":
    unittest.main()
