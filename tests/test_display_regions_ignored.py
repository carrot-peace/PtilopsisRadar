# coding=utf-8
"""
PR8a + PR8b + PR8c：display config 不再改变 canonical runtime output。

PR8a 验证 trendradar/__main__.py 中以下旧 gate 已被移除：

  Case A: AI_ANALYSIS=false 不再清空 AI result（current/incremental 也传递真实 ai_result）
  Case C: HOTLIST/NEW_ITEMS=false 不影响 canonical report data 传入（data 始终进入 pipeline）
  Case D: RSS=false 不再跳过 RSS 关键词分析（_process_rss_data_by_mode 始终执行分析）

PR8b 验证 AppContext 层不再消费 display config 改变 canonical structure：

  show_new_section: 始终返回 True（忽略 DISPLAY.REGIONS.NEW_ITEMS）
  region_order: 始终返回固定 canonical 顺序（忽略 DISPLAY.REGION_ORDER）

PR8c 验证 standalone_data 不再进入 canonical output：

  Case B: standalone_data 不再传入 generate_html（canonical output 不含 standalone section）
  region_order: 不含 standalone

测试方式（subprocess 隔离）：
  每个测试在独立子进程中加载 stub + 真实模块，不污染当前进程 sys.modules。
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
    # trendradar.cr.dispatch_mode is pure (no external deps).  Provide a
    # minimal stub so resolve_cr_dispatch_mode returns "off" in tests.
    _dm = types.ModuleType("trendradar.cr.dispatch_mode")
    _dm.resolve_cr_dispatch_mode = lambda env: "off"
    sys.modules["trendradar.cr.dispatch_mode"] = _dm

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


# ── Case B: PR8c: standalone_data 不再进入 canonical HTML output ──

class TestStandaloneRemovedFromCanonicalOutput(unittest.TestCase):
    """PR8c: standalone_data 不再传入 generate_html，canonical output 不含 standalone section。"""

    def test_daily_standalone_data_not_passed_to_html(self):
        """daily 模式 → generate_html 不再收到 standalone_data 参数。"""
        code = _PREAMBLE_AI_GATE + """
fake, html_calls, dashboard_calls = _build(mode="daily", ai_analysis_region=True, ai_result=USABLE_AI)
_run_pipeline(fake, "daily")
assert len(html_calls) == 1
assert "standalone_data" not in html_calls[0], "standalone_data should not be passed to generate_html"
"""
        result = _run_in_subprocess(code)
        self.assertEqual(
            result.returncode, 0,
            f"Subprocess failed:\nstdout: {result.stdout}\nstderr: {result.stderr}"
        )

    def test_standalone_false_ignored_for_canonical_output(self):
        """STANDALONE=false + daily → generate_html 仍不收到 standalone_data。"""
        code = _PREAMBLE_AI_GATE + """
fake, html_calls, dashboard_calls = _build(mode="daily", ai_analysis_region=True, ai_result=USABLE_AI)
fake.ctx.config["DISPLAY"]["REGIONS"]["STANDALONE"] = False
_run_pipeline(fake, "daily")
assert len(html_calls) == 1
assert "standalone_data" not in html_calls[0], "standalone_data should not be passed to generate_html"
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
_run_pipeline(fake, "daily")
assert len(all_calls) == 1, "generate_html should be called once"
kwargs = all_calls[0][1]
assert "new_titles" in kwargs, "new_titles should be passed as keyword arg"
"""
        result = _run_in_subprocess(code)
        self.assertEqual(
            result.returncode, 0,
            f"Subprocess failed:\nstdout: {result.stdout}\nstderr: {result.stderr}"
        )


# ── PR8b: show_new_section / region_order 忽略 display config ──

_PREAMBLE_PR8B = f"""
import os, sys, types, importlib.util
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

# stub heavy dependencies
_stub_pkg("requests", is_pkg=False)
_stub_pkg("trendradar")
_stub_pkg("trendradar.utils")
_stub_pkg("trendradar.utils.time")
_stub_pkg("trendradar.core")
_stub_pkg("trendradar.core.analyzer")
_stub_pkg("trendradar.core.scheduler")
_stub_pkg("trendradar.core.cdn")
_stub_pkg("trendradar.report")
_stub_pkg("trendradar.report.daily_v2")
_stub_pkg("trendradar.report.newsletter")
_stub_pkg("trendradar.report.dashboard")
_stub_pkg("trendradar.report.generator")
_stub_pkg("trendradar.crawler")
_stub_pkg("trendradar.storage")
_stub_pkg("trendradar.ai")
_stub_pkg("trendradar.ai.filter")
_stub_pkg("trendradar.telegram_bot")
_stub_pkg("trendradar.telegram_bot.access")

spec = importlib.util.spec_from_file_location(
    "trendradar.context", os.path.join(ROOT, "trendradar/context.py")
)
_ctx_mod = importlib.util.module_from_spec(spec)
sys.modules["trendradar.context"] = _ctx_mod
spec.loader.exec_module(_ctx_mod)
AppContext = _ctx_mod.AppContext
"""


class TestShowNewSectionAlwaysTrue(unittest.TestCase):
    """PR8b: show_new_section 始终返回 True，忽略 display config。"""

    def test_new_items_false_ignored(self):
        """DISPLAY.REGIONS.NEW_ITEMS=false → show_new_section 仍为 True。"""
        code = _PREAMBLE_PR8B + """
ctx = AppContext({"DISPLAY": {"REGIONS": {"NEW_ITEMS": False}}})
assert ctx.show_new_section is True, f"Expected True, got {{ctx.show_new_section!r}}"
"""
        result = _run_in_subprocess(code)
        self.assertEqual(
            result.returncode, 0,
            f"Subprocess failed:\nstdout: {result.stdout}\nstderr: {result.stderr}"
        )

    def test_new_items_true_still_true(self):
        """DISPLAY.REGIONS.NEW_ITEMS=true → show_new_section 仍为 True。"""
        code = _PREAMBLE_PR8B + """
ctx = AppContext({"DISPLAY": {"REGIONS": {"NEW_ITEMS": True}}})
assert ctx.show_new_section is True, f"Expected True, got {{ctx.show_new_section!r}}"
"""
        result = _run_in_subprocess(code)
        self.assertEqual(
            result.returncode, 0,
            f"Subprocess failed:\nstdout: {result.stdout}\nstderr: {result.stderr}"
        )

    def test_no_display_config_still_true(self):
        """无 DISPLAY config → show_new_section 仍为 True。"""
        code = _PREAMBLE_PR8B + """
ctx = AppContext({})
assert ctx.show_new_section is True, f"Expected True, got {{ctx.show_new_section!r}}"
"""
        result = _run_in_subprocess(code)
        self.assertEqual(
            result.returncode, 0,
            f"Subprocess failed:\nstdout: {result.stdout}\nstderr: {result.stderr}"
        )


class TestRegionOrderCanonicalFixed(unittest.TestCase):
    """PR8b: region_order 返回固定 canonical 顺序，忽略 display config。"""

    def test_custom_region_order_ignored(self):
        """DISPLAY.REGION_ORDER 反常排序 → region_order 仍为 canonical。"""
        code = _PREAMBLE_PR8B + """
ctx = AppContext({"DISPLAY": {"REGION_ORDER": ["ai_analysis", "standalone", "new_items", "rss", "hotlist"]}})
expected = ["hotlist", "rss", "new_items", "ai_analysis"]
assert ctx.region_order == expected, f"Expected {{expected}}, got {{ctx.region_order!r}}"
"""
        result = _run_in_subprocess(code)
        self.assertEqual(
            result.returncode, 0,
            f"Subprocess failed:\nstdout: {result.stdout}\nstderr: {result.stderr}"
        )

    def test_empty_region_order_ignored(self):
        """DISPLAY.REGION_ORDER=[] → region_order 仍为 canonical。"""
        code = _PREAMBLE_PR8B + """
ctx = AppContext({"DISPLAY": {"REGION_ORDER": []}})
expected = ["hotlist", "rss", "new_items", "ai_analysis"]
assert ctx.region_order == expected, f"Expected {{expected}}, got {{ctx.region_order!r}}"
"""
        result = _run_in_subprocess(code)
        self.assertEqual(
            result.returncode, 0,
            f"Subprocess failed:\nstdout: {result.stdout}\nstderr: {result.stderr}"
        )

    def test_no_region_order_config_still_canonical(self):
        """无 REGION_ORDER config → region_order 仍为 canonical。"""
        code = _PREAMBLE_PR8B + """
ctx = AppContext({})
expected = ["hotlist", "rss", "new_items", "ai_analysis"]
assert ctx.region_order == expected, f"Expected {{expected}}, got {{ctx.region_order!r}}"
"""
        result = _run_in_subprocess(code)
        self.assertEqual(
            result.returncode, 0,
            f"Subprocess failed:\nstdout: {result.stdout}\nstderr: {result.stderr}"
        )


class TestLegacyConfigNotBreaking(unittest.TestCase):
    """PR8b: 旧 display config 同时存在时 AppContext 不崩溃。"""

    def test_both_legacy_configs_no_crash(self):
        """同时设置 NEW_ITEMS=false + 反常 REGION_ORDER → 不崩溃，canonical 输出稳定。"""
        code = _PREAMBLE_PR8B + """
ctx = AppContext({
    "DISPLAY": {
        "REGIONS": {"NEW_ITEMS": False},
        "REGION_ORDER": ["ai_analysis", "standalone", "new_items", "rss", "hotlist"],
    }
})
assert ctx.show_new_section is True
expected_order = ["hotlist", "rss", "new_items", "ai_analysis"]
assert ctx.region_order == expected_order
"""
        result = _run_in_subprocess(code)
        self.assertEqual(
            result.returncode, 0,
            f"Subprocess failed:\nstdout: {result.stdout}\nstderr: {result.stderr}"
        )


# ── PR8f: display_mode=platform runtime behavior removed ──

class TestDisplayModeAlwaysCanonical(unittest.TestCase):
    """PR8f: display_mode 固定返回 "canonical"，忽略 config DISPLAY_MODE。"""

    def test_platform_config_returns_canonical(self):
        """DISPLAY_MODE=platform → display_mode 仍为 "canonical"。"""
        code = _PREAMBLE_PR8B + """
ctx = AppContext({"DISPLAY_MODE": "platform"})
assert ctx.display_mode == "canonical", f"Expected 'canonical', got {ctx.display_mode!r}"
"""
        result = _run_in_subprocess(code)
        self.assertEqual(
            result.returncode, 0,
            f"Subprocess failed:\nstdout: {result.stdout}\nstderr: {result.stderr}"
        )

    def test_keyword_config_returns_canonical(self):
        """DISPLAY_MODE=keyword → display_mode 仍为 "canonical"。"""
        code = _PREAMBLE_PR8B + """
ctx = AppContext({"DISPLAY_MODE": "keyword"})
assert ctx.display_mode == "canonical", f"Expected 'canonical', got {ctx.display_mode!r}"
"""
        result = _run_in_subprocess(code)
        self.assertEqual(
            result.returncode, 0,
            f"Subprocess failed:\nstdout: {result.stdout}\nstderr: {result.stderr}"
        )

    def test_missing_display_mode_returns_canonical(self):
        """无 DISPLAY_MODE config → display_mode 仍为 "canonical"。"""
        code = _PREAMBLE_PR8B + """
ctx = AppContext({})
assert ctx.display_mode == "canonical", f"Expected 'canonical', got {ctx.display_mode!r}"
"""
        result = _run_in_subprocess(code)
        self.assertEqual(
            result.returncode, 0,
            f"Subprocess failed:\nstdout: {result.stdout}\nstderr: {result.stderr}"
        )


class TestPlatformConversionRemoved(unittest.TestCase):
    """PR8f: __main__.py 不再导入或调用 convert_keyword_stats_to_platform_stats。"""

    def test_main_module_has_no_platform_conversion_import(self):
        """__main__.py 源码中不包含 convert_keyword_stats_to_platform_stats 导入。"""
        code = f"""
import os
main_path = os.path.join({ROOT!r}, "trendradar", "__main__.py")
with open(main_path, "r") as f:
    source = f.read()
# Should not import convert_keyword_stats_to_platform_stats
assert "convert_keyword_stats_to_platform_stats" not in source, \\
    "__main__.py still references convert_keyword_stats_to_platform_stats"
"""
        result = _run_in_subprocess(code)
        self.assertEqual(
            result.returncode, 0,
            f"Subprocess failed:\nstdout: {result.stdout}\nstderr: {result.stderr}"
        )

    def test_main_module_has_no_display_mode_branch(self):
        """__main__.py 源码中不包含 display_mode == 'platform' 分支。"""
        code = f"""
import os
main_path = os.path.join({ROOT!r}, "trendradar", "__main__.py")
with open(main_path, "r") as f:
    source = f.read()
assert 'display_mode == "platform"' not in source, \\
    "__main__.py still has display_mode == 'platform' branch"
assert "display_mode == 'platform'" not in source, \\
    "__main__.py still has display_mode == 'platform' branch"
"""
        result = _run_in_subprocess(code)
        self.assertEqual(
            result.returncode, 0,
            f"Subprocess failed:\nstdout: {result.stdout}\nstderr: {result.stderr}"
        )

    def test_convert_function_removed_from_core(self):
        """PR8 final audit: orphaned convert_keyword_stats_to_platform_stats 已从 core/analyzer.py 删除（无 caller）。"""
        code = f"""
import os
analyzer_path = os.path.join({ROOT!r}, "trendradar", "core", "analyzer.py")
with open(analyzer_path, "r") as f:
    source = f.read()
assert "def convert_keyword_stats_to_platform_stats" not in source, \\
    "convert_keyword_stats_to_platform_stats should be removed from core/analyzer.py (orphaned, no caller)"
"""
        result = _run_in_subprocess(code)
        self.assertEqual(
            result.returncode, 0,
            f"Subprocess failed:\nstdout: {result.stdout}\nstderr: {result.stderr}"
        )


if __name__ == "__main__":
    unittest.main()
