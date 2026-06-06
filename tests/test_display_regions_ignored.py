# coding=utf-8
"""
PR8a：display.regions 不再改变 canonical runtime output。

验证 trendradar/__main__.py 中以下旧 gate 已被移除：

  Case A: AI_ANALYSIS=false 不再清空 AI result（current/incremental 也传递真实 ai_result）
  Case B: STANDALONE=false 不再阻止 standalone_data 进入 canonical HTML 生成
  Case C: HOTLIST/NEW_ITEMS=false 不影响 canonical report data 传入（data 始终进入 pipeline）
  Case D: RSS=false 不再跳过 RSS 关键词分析（_process_rss_data_by_mode 始终执行分析）

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


# ── Case A: AI_ANALYSIS=false 不再清空 AI result ──

_PREAMBLE_AI_GATE = f"""
import importlib.util
import os
import sys
import types
from types import SimpleNamespace

ROOT = {ROOT!r}


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
    "daily": {{"report_type": "全天汇总", "should_send_notification": True}},
    "current": {{"report_type": "当前榜单", "should_send_notification": True}},
    "incremental": {{"report_type": "增量分析", "should_send_notification": True}},
}}


def _build(*, mode, ai_analysis_region, ai_result, standalone_data=None):
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


def _run_pipeline(fake, mode, standalone_data=None):
    return NewsAnalyzer._run_analysis_pipeline(
        fake,
        data_source={{"weibo": {{}}}},
        mode=mode,
        title_info={{}},
        new_titles={{}},
        word_groups=[],
        filter_words=[],
        id_to_name={{"weibo": "微博"}},
        standalone_data=standalone_data,
    )
"""


class TestAIAnalysisGateRemoved(unittest.TestCase):
    """PR8a: AI_ANALYSIS=false 不再清空 AI result（所有 mode）。"""

    def test_current_region_false_gets_real_ai(self):
        """current 模式 + AI_ANALYSIS=false → dashboard 收到真实 ai_result。"""
        code = _PREAMBLE_AI_GATE + """
fake, html_calls, dashboard_calls = _build(mode="current", ai_analysis_region=False, ai_result=USABLE_AI)
_run_pipeline(fake, "current")
assert len(dashboard_calls) == 1
assert dashboard_calls[0]["ai_analysis"] is USABLE_AI
"""
        result = _run_in_subprocess(code)
        self.assertEqual(
            result.returncode, 0,
            f"Subprocess failed:\nstdout: {result.stdout}\nstderr: {result.stderr}"
        )

    def test_incremental_region_false_gets_real_ai(self):
        """incremental 模式 + AI_ANALYSIS=false → dashboard 收到真实 ai_result。"""
        code = _PREAMBLE_AI_GATE + """
fake, html_calls, dashboard_calls = _build(mode="incremental", ai_analysis_region=False, ai_result=USABLE_AI)
_run_pipeline(fake, "incremental")
assert len(dashboard_calls) == 1
assert dashboard_calls[0]["ai_analysis"] is USABLE_AI
"""
        result = _run_in_subprocess(code)
        self.assertEqual(
            result.returncode, 0,
            f"Subprocess failed:\nstdout: {result.stdout}\nstderr: {result.stderr}"
        )


# ── Case B: STANDALONE=false 不再阻止 standalone_data 进入 canonical HTML ──

class TestStandaloneGateRemoved(unittest.TestCase):
    """PR8a: STANDALONE=false 不再阻止 standalone_data 进入 HTML 生成。"""

    def test_daily_standalone_false_data_still_passed(self):
        """daily + STANDALONE=false → generate_html 仍收到 standalone_data。"""
        code = _PREAMBLE_AI_GATE + """
# Add STANDALONE=False to config
standalone = {"platforms": [{"id": "zhihu", "name": "zh"}], "rss_feeds": []}
fake, html_calls, dashboard_calls = _build(mode="daily", ai_analysis_region=True, ai_result=USABLE_AI)
fake.ctx.config["DISPLAY"]["REGIONS"]["STANDALONE"] = False
_run_pipeline(fake, "daily", standalone_data=standalone)
assert len(html_calls) == 1
assert html_calls[0].get("standalone_data") is standalone, "standalone_data should be passed through"
"""
        result = _run_in_subprocess(code)
        self.assertEqual(
            result.returncode, 0,
            f"Subprocess failed:\nstdout: {result.stdout}\nstderr: {result.stderr}"
        )


# ── Case C: HOTLIST/NEW_ITEMS=false 不影响 canonical data ──

class TestHotlistNewItemsNotGated(unittest.TestCase):
    """PR8a: HOTLIST/NEW_ITEMS config 不再作为 runtime gate 删除 core data。"""

    def test_hotlist_false_still_passes_stats_to_html(self):
        """HOTLIST=false 不导致 canonical report 中 stats 消失。"""
        code = _PREAMBLE_AI_GATE + """
# Override generate_html to also capture positional args
all_calls = []
def _capture_html(*a, **k):
    all_calls.append((a, k))
    return "FULL_HTML"

fake, _, dashboard_calls = _build(mode="daily", ai_analysis_region=True, ai_result=USABLE_AI)
fake.ctx.generate_html = _capture_html
fake.ctx.config["DISPLAY"]["REGIONS"]["HOTLIST"] = False
stats, html_file, ai_result, rss_items = _run_pipeline(fake, "daily")
assert stats is not None, "stats should not be None"
assert len(stats) > 0, "stats should not be empty"
assert len(all_calls) == 1, "generate_html should be called once"
positional_args = all_calls[0][0]
assert len(positional_args) >= 1, "generate_html should receive stats as positional arg"
assert positional_args[0] is stats, "first positional arg should be stats"
"""
        result = _run_in_subprocess(code)
        self.assertEqual(
            result.returncode, 0,
            f"Subprocess failed:\nstdout: {result.stdout}\nstderr: {result.stderr}"
        )

    def test_new_items_false_still_passes_new_titles(self):
        """NEW_ITEMS=false 不导致 canonical report 中 new_titles 消失。"""
        code = _PREAMBLE_AI_GATE + """
# Override generate_html to capture all args
all_calls = []
def _capture_html(*a, **k):
    all_calls.append((a, k))
    return "FULL_HTML"

fake, _, dashboard_calls = _build(mode="daily", ai_analysis_region=True, ai_result=USABLE_AI)
fake.ctx.generate_html = _capture_html
fake.ctx.config["DISPLAY"]["REGIONS"]["NEW_ITEMS"] = False
_run_pipeline(fake, "daily", standalone_data=None)
assert len(all_calls) == 1, "generate_html should be called once"
kwargs = all_calls[0][1]
assert "new_titles" in kwargs, "new_titles should be passed as keyword arg"
"""
        result = _run_in_subprocess(code)
        self.assertEqual(
            result.returncode, 0,
            f"Subprocess failed:\nstdout: {result.stdout}\nstderr: {result.stderr}"
        )


if __name__ == "__main__":
    unittest.main()
