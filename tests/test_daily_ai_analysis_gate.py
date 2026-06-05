# coding=utf-8
"""
PR4a：daily full report 在传递 ai_result 时忽略 DISPLAY.REGIONS.AI_ANALYSIS gate。

验证 trendradar/__main__.py 里 _run_analysis_pipeline 的 HTML 生成分流：

  - mode == "daily"        → 始终把原始 ai_result 传给 generate_html(ai_analysis=...)，
                             不因 DISPLAY.REGIONS.AI_ANALYSIS=false 被置空（daily full
                             report 是固定产品输出，AI 是否显示由 renderer 决定）。
  - current / incremental  → 维持旧 gate：AI_ANALYSIS=false 时 dashboard 收到 None。

测试方式（不经端到端，不跑真实 crawler / AI / Telegram）：
  - 按 routing 测试同款思路，把 __main__ 的重依赖 import 成占位 stub，按文件路径加载
    真实 trendradar.__main__，取出真实 NewsAnalyzer 类；
  - 不实例化（__init__ 很重），改为构造最小 fake self，调用未绑定的
    NewsAnalyzer._run_analysis_pipeline，把 self.ctx.generate_html /
    generate_dashboard spy 起来，断言传入的 ai_analysis。
"""

import importlib.util
import os
import sys
import types
import unittest
from types import SimpleNamespace

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _attach_getattr(mod):
    """让 stub 模块对任意名字返回占位类（兼容 `from mod import Name`）。"""

    def __getattr__(name):  # PEP 562 module-level __getattr__
        obj = type(name, (), {})
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
    """stub 掉 __main__ 的重依赖后，按文件路径加载真实 trendradar.__main__。"""
    # 顶层第三方依赖
    _stub_pkg("requests", is_pkg=False)

    # trendradar 包与子模块：本测试路径不会真正调用它们，占位即可
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

    spec = importlib.util.spec_from_file_location(
        "trendradar.__main__", os.path.join(ROOT, "trendradar/__main__.py")
    )
    mod = importlib.util.module_from_spec(spec)
    sys.modules["trendradar.__main__"] = mod
    spec.loader.exec_module(mod)
    return mod


_MAIN = _load_main_module()
NewsAnalyzer = _MAIN.NewsAnalyzer

# 可识别 sentinel，代表“已成功生成、可用”的 environment AI result
USABLE_AI = object()


class _GateTestBase(unittest.TestCase):
    def _build(self, *, ai_analysis_region, ai_result):
        """构造最小 fake self + ctx，并 spy 住两个 HTML 生成入口。"""
        self.html_calls = []
        self.dashboard_calls = []

        config = {
            "AI_ANALYSIS": {"ENABLED": True},
            "STORAGE": {"FORMATS": {"HTML": True}},
            "DISPLAY": {"REGIONS": {"AI_ANALYSIS": ai_analysis_region}},
            "SHOW_VERSION_UPDATE": False,
        }

        ctx = SimpleNamespace(
            config=config,
            display_mode="keyword",
            platform_ids=["weibo"],
            count_frequency=lambda *a, **k: ([{"word": "x", "count": 1, "titles": []}], 5),
            generate_html=lambda *a, **k: (self.html_calls.append(k) or "FULL_HTML"),
            generate_dashboard=lambda *a, **k: self.dashboard_calls.append(k),
        )

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
            _get_mode_strategy=lambda: {"report_type": "daily"},
            _run_ai_analysis=lambda *a, **k: ai_result,
        )
        return fake

    def _run(self, fake, mode):
        return NewsAnalyzer._run_analysis_pipeline(
            fake,
            data_source={"weibo": {}},
            mode=mode,
            title_info={},
            new_titles={},
            word_groups=[],
            filter_words=[],
            id_to_name={"weibo": "微博"},
        )


class TestDailyGate(_GateTestBase):
    def test_daily_region_false_usable_ai_passes_through(self):
        # daily + AI_ANALYSIS=false + 可用 ai_result → 仍传入原始 ai_result，不置空
        fake = self._build(ai_analysis_region=False, ai_result=USABLE_AI)
        self._run(fake, "daily")
        self.assertEqual(len(self.html_calls), 1)
        self.assertEqual(len(self.dashboard_calls), 0)
        self.assertIs(self.html_calls[0]["ai_analysis"], USABLE_AI)

    def test_daily_region_true_usable_ai_unchanged(self):
        # daily + AI_ANALYSIS=true + 可用 ai_result → 行为不变，仍传原始 ai_result
        fake = self._build(ai_analysis_region=True, ai_result=USABLE_AI)
        self._run(fake, "daily")
        self.assertEqual(len(self.html_calls), 1)
        self.assertIs(self.html_calls[0]["ai_analysis"], USABLE_AI)

    def test_daily_region_false_no_ai_result_passes_none(self):
        # daily + AI_ANALYSIS=false + 无可用 AI → 传入 None，由 PR3a/PR3b fallback 处理；不 crash
        fake = self._build(ai_analysis_region=False, ai_result=None)
        self._run(fake, "daily")
        self.assertEqual(len(self.html_calls), 1)
        self.assertIsNone(self.html_calls[0]["ai_analysis"])


class TestNonDailyGateUnchanged(_GateTestBase):
    def test_current_region_false_dashboard_gets_none(self):
        # current + AI_ANALYSIS=false + 可用 ai_result → 仍按旧 gate 置空
        fake = self._build(ai_analysis_region=False, ai_result=USABLE_AI)
        self._run(fake, "current")
        self.assertEqual(len(self.dashboard_calls), 1)
        self.assertEqual(len(self.html_calls), 0)
        self.assertIsNone(self.dashboard_calls[0]["ai_analysis"])

    def test_current_region_true_dashboard_gets_ai(self):
        # current + AI_ANALYSIS=true + 可用 ai_result → dashboard 仍收到原始 ai_result
        fake = self._build(ai_analysis_region=True, ai_result=USABLE_AI)
        self._run(fake, "current")
        self.assertEqual(len(self.dashboard_calls), 1)
        self.assertIs(self.dashboard_calls[0]["ai_analysis"], USABLE_AI)


if __name__ == "__main__":
    unittest.main()
