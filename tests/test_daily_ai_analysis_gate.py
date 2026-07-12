# coding=utf-8
"""
PR4a + PR8a：所有 canonical output 在传递 ai_result 时忽略 DISPLAY.REGIONS.AI_ANALYSIS gate。

验证 trendradar/__main__.py 里 _run_analysis_pipeline 的 HTML 生成分流：

  - mode == "daily"        → 始终把原始 ai_result 传给 generate_html(ai_analysis=...)，
                             不因 DISPLAY.REGIONS.AI_ANALYSIS=false 被置空。
  - current / incremental  → PR8a 起同样忽略 gate，dashboard 始终收到真实 ai_result。

测试方式（subprocess 隔离）：
  每个测试在独立子进程中加载 stub + 真实 trendradar.__main__，不污染当前进程 sys.modules。
"""

import os
import subprocess
import sys
import textwrap
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


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
from types import SimpleNamespace

ROOT = {ROOT!r}

sys.path.insert(0, os.path.join(ROOT, "tests"))
import _bootstrap


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


def _load_main_module():
    _stub_pkg("requests", is_pkg=False)
    _stub_pkg("trendradar")
    _stub_pkg("trendradar.context")
    _stub_pkg("trendradar.core")
    _stub_pkg("trendradar.core.analyzer")
    _stub_pkg("trendradar.core.scheduler")
    _stub_pkg("trendradar.core.cdn")
    _stub_pkg("trendradar.crawler")
    _stub_pkg("trendradar.storage")
    _stub_pkg("trendradar.utils")
    _stub_pkg("trendradar.utils.time")
    _stub_pkg("trendradar.ai")
    _stub_pkg("trendradar.telegram_bot")
    _stub_pkg("trendradar.telegram_bot.access")
    _bootstrap.install_cr_dispatch_mode_stub()

    spec = importlib.util.spec_from_file_location(
        "trendradar.__main__", os.path.join(ROOT, "trendradar/__main__.py")
    )
    mod = importlib.util.module_from_spec(spec)
    sys.modules["trendradar.__main__"] = mod
    spec.loader.exec_module(mod)
    return mod


_MAIN = _load_main_module()
NewsAnalyzer = _MAIN.NewsAnalyzer

USABLE_AI = object()

_MODE_STRATEGY = {{
    "daily": {{"report_type": "全天汇总", "should_send_notification": False}},
    "current": {{"report_type": "当前榜单", "should_send_notification": False}},
    "incremental": {{"report_type": "增量分析", "should_send_notification": False}},
}}


def _build(*, mode, ai_analysis_region, ai_result):
    html_calls = []
    dashboard_calls = []

    config = {{
        "AI_ANALYSIS": {{"ENABLED": True}},
        "STORAGE": {{"FORMATS": {{"HTML": True}}}},
        "DISPLAY": {{"REGIONS": {{"AI_ANALYSIS": ai_analysis_region}}}},
        "SHOW_VERSION_UPDATE": False,
    }}

    ctx = SimpleNamespace(
        config=config,
        display_mode="keyword",
        platform_ids=["weibo"],
        count_frequency=lambda *a, **k: ([{{"word": "x", "count": 1, "titles": []}}], 5),
        generate_html=lambda *a, **k: (html_calls.append(k) or "FULL_HTML"),
        generate_dashboard=lambda *a, **k: dashboard_calls.append(k),
    )

    strategy = _MODE_STRATEGY[mode]
    fake = SimpleNamespace(
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
    return fake, html_calls, dashboard_calls


def _run_pipeline(fake, mode):
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


class TestDailyGate(unittest.TestCase):
    """PR4a: daily full report 在 AI_ANALYSIS=false 时仍使用真实 ai_result。"""

    def test_daily_region_false_usable_ai_passes_through(self):
        code = _SUBPROCESS_PREAMBLE + """
fake, html_calls, dashboard_calls = _build(mode="daily", ai_analysis_region=False, ai_result=USABLE_AI)
_run_pipeline(fake, "daily")
assert len(html_calls) == 1, f"Expected 1 html call, got {len(html_calls)}"
assert len(dashboard_calls) == 0, f"Expected 0 dashboard calls, got {len(dashboard_calls)}"
assert html_calls[0]["ai_analysis"] is USABLE_AI, "ai_analysis should be USABLE_AI"
"""
        result = _run_in_subprocess(code)
        self.assertEqual(
            result.returncode, 0,
            f"Subprocess failed:\nstdout: {result.stdout}\nstderr: {result.stderr}"
        )

    def test_daily_region_true_usable_ai_unchanged(self):
        code = _SUBPROCESS_PREAMBLE + """
fake, html_calls, dashboard_calls = _build(mode="daily", ai_analysis_region=True, ai_result=USABLE_AI)
_run_pipeline(fake, "daily")
assert len(html_calls) == 1
assert html_calls[0]["ai_analysis"] is USABLE_AI
"""
        result = _run_in_subprocess(code)
        self.assertEqual(
            result.returncode, 0,
            f"Subprocess failed:\nstdout: {result.stdout}\nstderr: {result.stderr}"
        )

    def test_daily_region_false_no_ai_result_passes_none(self):
        code = _SUBPROCESS_PREAMBLE + """
fake, html_calls, dashboard_calls = _build(mode="daily", ai_analysis_region=False, ai_result=None)
_run_pipeline(fake, "daily")
assert len(html_calls) == 1
assert html_calls[0]["ai_analysis"] is None
"""
        result = _run_in_subprocess(code)
        self.assertEqual(
            result.returncode, 0,
            f"Subprocess failed:\nstdout: {result.stdout}\nstderr: {result.stderr}"
        )


class TestNonDailyGateUpdated(unittest.TestCase):
    """PR8a: current / incremental 不再受 AI_ANALYSIS gate 影响。"""

    def test_current_region_false_dashboard_gets_real_ai(self):
        code = _SUBPROCESS_PREAMBLE + """
fake, html_calls, dashboard_calls = _build(mode="current", ai_analysis_region=False, ai_result=USABLE_AI)
_run_pipeline(fake, "current")
assert len(dashboard_calls) == 1
assert len(html_calls) == 0
assert dashboard_calls[0]["ai_analysis"] is USABLE_AI
"""
        result = _run_in_subprocess(code)
        self.assertEqual(
            result.returncode, 0,
            f"Subprocess failed:\nstdout: {result.stdout}\nstderr: {result.stderr}"
        )

    def test_current_region_true_dashboard_gets_ai(self):
        code = _SUBPROCESS_PREAMBLE + """
fake, html_calls, dashboard_calls = _build(mode="current", ai_analysis_region=True, ai_result=USABLE_AI)
_run_pipeline(fake, "current")
assert len(dashboard_calls) == 1
assert dashboard_calls[0]["ai_analysis"] is USABLE_AI
"""
        result = _run_in_subprocess(code)
        self.assertEqual(
            result.returncode, 0,
            f"Subprocess failed:\nstdout: {result.stdout}\nstderr: {result.stderr}"
        )


if __name__ == "__main__":
    unittest.main()
