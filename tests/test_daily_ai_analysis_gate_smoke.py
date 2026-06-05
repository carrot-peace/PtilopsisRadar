# coding=utf-8
"""
PR4a smoke / regression tests。

验证 __main__._run_analysis_pipeline → context.render_html →
newsletter.render_newsletter_report 完整链路中 AI analysis gate 行为
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
     → 旧行为保持：dashboard 仍收到 ai_analysis=None

  4. Telegram daily attachment path 稳定性
     → daily_digest 附件路径指向 public/daily/full.html
     → 不发送真实 Telegram 请求，不访问网络
"""

import importlib.util
import os
import sys
import types
import unittest
from datetime import datetime
from types import SimpleNamespace

sys.path.insert(0, os.path.dirname(__file__))
import _bootstrap  # noqa: E402

ROOT = _bootstrap.ROOT

_BOOT = _bootstrap.load_all()
AIAnalysisResult = _BOOT.analyzer.AIAnalysisResult

FALLBACK_NOTICE = (
    "本轮 AI 分析不可用；本报告仅展示程序已采集内容和可用元数据，不生成额外结论。"
)

# ── 模块加载工具 ─────────────────────────────────────────────────────────────


def _attach_getattr(mod):
    def __getattr__(name):
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


def _load_real(name, relpath):
    spec = importlib.util.spec_from_file_location(name, os.path.join(ROOT, relpath))
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


# ── 加载真实 context（render_html 端到端用）────────────────────────────────

_stub_pkg("trendradar.report")
_load_real("trendradar.report.newsletter", "trendradar/report/newsletter.py")
_stub_pkg("trendradar.report.dashboard")
_stub_pkg("trendradar.utils")
_stub_pkg("trendradar.utils.time")
_stub_pkg("trendradar.core")
_stub_pkg("trendradar.notification")
_stub_pkg("trendradar.ai")
_stub_pkg("trendradar.ai.filter")
_stub_pkg("trendradar.storage")

_CTX = _load_real("trendradar.context", "trendradar/context.py")
AppContext = _CTX.AppContext

# ── 加载真实 __main__（pipeline 级别测试用）─────────────────────────────────

_stub_pkg("requests", is_pkg=False)
_stub_pkg("trendradar")
_stub_pkg("trendradar.context")
_stub_pkg("trendradar.core.analyzer")
_stub_pkg("trendradar.core.scheduler")
_stub_pkg("trendradar.core.cdn")
_stub_pkg("trendradar.crawler")

_MAIN = _load_real("trendradar.__main__", "trendradar/__main__.py")
NewsAnalyzer = _MAIN.NewsAnalyzer

# ── helpers ──────────────────────────────────────────────────────────────────


def _load_real_senders():
    """加载真实 senders 模块（覆盖可能由其他测试注册的 stub）。"""
    _load_real("trendradar.notification.batch", "trendradar/notification/batch.py")
    _load_real("trendradar.notification.formatters", "trendradar/notification/formatters.py")
    return _load_real("trendradar.notification.senders", "trendradar/notification/senders.py")


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


def _make_ai_result(**overrides):
    defaults = dict(
        success=True,
        report_style="environment",
        overview="今日盘面平稳",
        overview_stats={"anomaly": 2, "cross_layer": 1},
        cross_layer_verified=[{"title": "跨层信号", "sources": ["微博", "BBC"]}],
    )
    defaults.update(overrides)
    return AIAnalysisResult(**defaults)


def _stats_with_titles():
    """非空 stats + total_titles，保证 pipeline 进入 AI 分析分支。"""
    return [
        {
            "word": "示例关键词",
            "count": 1,
            "titles": [_bootstrap.make_title("某条热榜标题", "微博", 3)],
        }
    ], 1


def _run_pipeline(fake, mode="daily"):
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


# ── 1 & 2. daily full report AI analysis gate ───────────────────────────────


class TestDailyGateSmoke(unittest.TestCase):
    """PR4a: daily full report 在 AI_ANALYSIS=false 时仍使用真实 ai_result。"""

    # -- pipeline 层：验证 ai_analysis 参数传递 --

    def test_pipeline_daily_gate_false_passes_real_ai(self):
        """场景 1 pipeline：daily + AI_ANALYSIS=false + usable AI
        → generate_html 收到真实 ai_result（未被 gate 置空）。
        """
        ai = _make_ai_result(overview="跨层共振信号持续升温")
        html_calls = []
        dashboard_calls = []

        ctx = SimpleNamespace(
            config={
                "AI_ANALYSIS": {"ENABLED": True},
                "STORAGE": {"FORMATS": {"HTML": True}},
                "DISPLAY": {"REGIONS": {"AI_ANALYSIS": False}},
                "SHOW_VERSION_UPDATE": False,
            },
            display_mode="keyword",
            platform_ids=["weibo"],
            count_frequency=lambda *a, **k: _stats_with_titles(),
            generate_html=lambda *a, **k: (html_calls.append(k) or "HTML_OUT"),
            generate_dashboard=lambda *a, **k: dashboard_calls.append(k),
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
            _run_ai_analysis=lambda *a, **k: ai,
        )

        _run_pipeline(fake, "daily")

        self.assertEqual(len(html_calls), 1, "应调用 generate_html")
        self.assertEqual(len(dashboard_calls), 0, "不应调用 generate_dashboard")
        passed_ai = html_calls[0].get("ai_analysis")
        self.assertIs(passed_ai, ai, "ai_analysis 应为原始 ai_result，未被 gate 置空")

    def test_pipeline_daily_gate_false_none_ai_passes_none(self):
        """场景 2 pipeline：daily + AI_ANALYSIS=false + ai_result=None
        → generate_html 收到 None（由 renderer 处理 fallback），不 crash。
        """
        html_calls = []

        ctx = SimpleNamespace(
            config={
                "AI_ANALYSIS": {"ENABLED": True},
                "STORAGE": {"FORMATS": {"HTML": True}},
                "DISPLAY": {"REGIONS": {"AI_ANALYSIS": False}},
                "SHOW_VERSION_UPDATE": False,
            },
            display_mode="keyword",
            platform_ids=["weibo"],
            count_frequency=lambda *a, **k: _stats_with_titles(),
            generate_html=lambda *a, **k: (html_calls.append(k) or "HTML_OUT"),
            generate_dashboard=lambda *a, **k: None,
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
            _run_ai_analysis=lambda *a, **k: None,
        )

        # 不 crash
        _run_pipeline(fake, "daily")

        self.assertEqual(len(html_calls), 1)
        self.assertIsNone(html_calls[0].get("ai_analysis"))

    # -- HTML 内容层：端到端验证 newsletter 输出 --

    def test_html_daily_gate_false_with_usable_ai_contains_editorial(self):
        """场景 1 内容：daily + AI_ANALYSIS=false + usable AI
        → 输出包含 AI overview；不包含 fallback notice。
        """
        ai = _make_ai_result(overview="跨层共振信号持续升温")
        ctx = AppContext({"DISPLAY": {"REGIONS": {"AI_ANALYSIS": False}}})
        ctx.get_time = lambda: datetime(2026, 6, 5, 9, 0)

        out = ctx.render_html(_report_data(), 1, mode="daily", ai_analysis=ai)

        self.assertIn("<!DOCTYPE html>", out)
        self.assertIn("跨层共振信号持续升温", out)
        self.assertNotIn(FALLBACK_NOTICE, out)
        self.assertNotIn('<div class="ai-unavailable">', out)
        self.assertIn("某条热榜标题", out)  # 程序已采集内容照常展示

    def test_html_daily_gate_false_with_none_ai_contains_fallback(self):
        """场景 2 内容：daily + AI_ANALYSIS=false + ai_result=None
        → 输出包含 fallback notice；仍展示程序已采集内容。
        """
        ctx = AppContext({"DISPLAY": {"REGIONS": {"AI_ANALYSIS": False}}})
        ctx.get_time = lambda: datetime(2026, 6, 5, 9, 0)

        out = ctx.render_html(_report_data(), 1, mode="daily", ai_analysis=None)

        self.assertIn("<!DOCTYPE html>", out)
        self.assertIn(FALLBACK_NOTICE, out)
        self.assertIn('<div class="ai-unavailable">', out)
        self.assertIn("某条热榜标题", out)


# ── 3. current / incremental gate unchanged ─────────────────────────────────


class TestNonDailyGateUnchangedSmoke(unittest.TestCase):
    """PR4a: current / incremental 保持旧的 AI_ANALYSIS gate。"""

    def test_current_gate_false_dashboard_gets_none(self):
        """场景 3：current + AI_ANALYSIS=false + usable AI
        → dashboard 仍收到 ai_analysis=None。
        """
        ai = _make_ai_result()
        dashboard_calls = []

        ctx = SimpleNamespace(
            config={
                "AI_ANALYSIS": {"ENABLED": True},
                "STORAGE": {"FORMATS": {"HTML": True}},
                "DISPLAY": {"REGIONS": {"AI_ANALYSIS": False}},
                "SHOW_VERSION_UPDATE": False,
            },
            display_mode="keyword",
            platform_ids=["weibo"],
            count_frequency=lambda *a, **k: _stats_with_titles(),
            generate_html=lambda *a, **k: "HTML",
            generate_dashboard=lambda *a, **k: dashboard_calls.append(k),
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
            _run_ai_analysis=lambda *a, **k: ai,
        )

        _run_pipeline(fake, "current")

        self.assertEqual(len(dashboard_calls), 1)
        self.assertIsNone(dashboard_calls[0].get("ai_analysis"))

    def test_incremental_gate_false_dashboard_gets_none(self):
        """场景 3 变体：incremental + AI_ANALYSIS=false → 同 current 行为。"""
        ai = _make_ai_result()
        dashboard_calls = []

        ctx = SimpleNamespace(
            config={
                "AI_ANALYSIS": {"ENABLED": True},
                "STORAGE": {"FORMATS": {"HTML": True}},
                "DISPLAY": {"REGIONS": {"AI_ANALYSIS": False}},
                "SHOW_VERSION_UPDATE": False,
            },
            display_mode="keyword",
            platform_ids=["weibo"],
            count_frequency=lambda *a, **k: _stats_with_titles(),
            generate_html=lambda *a, **k: "HTML",
            generate_dashboard=lambda *a, **k: dashboard_calls.append(k),
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
            _run_ai_analysis=lambda *a, **k: ai,
        )

        _run_pipeline(fake, "incremental")

        self.assertEqual(len(dashboard_calls), 1)
        self.assertIsNone(dashboard_calls[0].get("ai_analysis"))


# ── 4. Telegram daily attachment path stability ─────────────────────────────


class TestTelegramDailyAttachmentPath(unittest.TestCase):
    """PR4a: daily attachment path 仍指向 public/daily/full.html。"""

    def setUp(self):
        # 每次测试前确保加载的是真实 senders（覆盖其他测试可能注册的 stub）
        self._senders = _load_real_senders()

    def test_daily_digest_attachment_path_stable(self):
        """场景 4：resolve_report_attachment_path('output', 'daily') 不变。"""
        path = self._senders.resolve_report_attachment_path("output", "daily")
        self.assertEqual(path, os.path.join("output", "public", "daily", "full.html"))

    def test_daily_digest_attachment_path_with_explicit_full(self):
        """场景 4 变体：显式 report_kind='full' 结果一致。"""
        path = self._senders.resolve_report_attachment_path("output", "daily", "full")
        self.assertEqual(path, os.path.join("output", "public", "daily", "full.html"))

    def test_daily_digest_event_defaults_to_full(self):
        """场景 4：daily_digest 事件默认附件类型为 full。"""
        kind = self._senders.resolve_attachment_kind_for_event({}, "daily_digest")
        self.assertEqual(kind, "full")


if __name__ == "__main__":
    unittest.main()
