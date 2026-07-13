# coding=utf-8
"""AI analysis scheduling semantics for NewsAnalyzer._run_ai_analysis."""

import os
import subprocess
import sys
import textwrap
import unittest


ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _run_in_subprocess(code: str):
    return subprocess.run(
        [sys.executable, "-c", textwrap.dedent(code)],
        capture_output=True,
        text=True,
        cwd=ROOT,
    )


_PREAMBLE = f"""
import importlib.util
import os
import sys
import types
from types import SimpleNamespace

ROOT = {ROOT!r}


def _stub_pkg(name, is_pkg=True):
    mod = types.ModuleType(name)
    if is_pkg:
        mod.__path__ = []
    sys.modules[name] = mod
    return mod


requests = _stub_pkg("requests", is_pkg=False)
trendradar = _stub_pkg("trendradar")
trendradar.__version__ = "test"
context = _stub_pkg("trendradar.context")
context.AppContext = object
core = _stub_pkg("trendradar.core")
core.load_config = lambda: {{}}
core.Scheduler = object
core_analyzer = _stub_pkg("trendradar.core.analyzer", is_pkg=False)
core_analyzer.strip_background_groups = lambda groups, prefix: groups
crawler = _stub_pkg("trendradar.crawler")
crawler.DataFetcher = object
storage = _stub_pkg("trendradar.storage")
storage.convert_crawl_results_to_news_data = lambda *a, **k: {{}}
utils = _stub_pkg("trendradar.utils")
time_mod = _stub_pkg("trendradar.utils.time", is_pkg=False)
time_mod.DEFAULT_TIMEZONE = "Asia/Shanghai"
time_mod.is_within_days = lambda *a, **k: True
time_mod.calculate_days_old = lambda *a, **k: 0
cdn = _stub_pkg("trendradar.core.cdn", is_pkg=False)
cdn.fetch_with_fallback = lambda *a, **k: None


class ResolvedSchedule:
    def __init__(
        self, period_key=None, period_name=None, day_plan="test",
        collect=True, analyze=True, report_mode="current",
        ai_mode="current", once_analyze=False,
        frequency_file=None, filter_method=None, interests_file=None,
    ):
        self.period_key = period_key
        self.period_name = period_name
        self.day_plan = day_plan
        self.collect = collect
        self.analyze = analyze
        self.report_mode = report_mode
        self.ai_mode = ai_mode
        self.once_analyze = once_analyze
        self.frequency_file = frequency_file
        self.filter_method = filter_method
        self.interests_file = interests_file


scheduler_mod = _stub_pkg("trendradar.core.scheduler", is_pkg=False)
scheduler_mod.ResolvedSchedule = ResolvedSchedule


class AIAnalysisResult:
    def __init__(self, success=False, skipped=False, error="", **kwargs):
        self.success = success
        self.skipped = skipped
        self.error = error
        self.ai_mode = ""
        for key, value in kwargs.items():
            setattr(self, key, value)


AI_CALLS = []


class AIAnalyzer:
    def __init__(self, ai_config, analysis_config, get_time, debug=False):
        self.ai_config = ai_config
        self.analysis_config = analysis_config

    def analyze(self, **kwargs):
        AI_CALLS.append(kwargs)
        return AIAnalysisResult(success=True)


ai_mod = _stub_pkg("trendradar.ai")
ai_mod.AIAnalyzer = AIAnalyzer
ai_mod.AIAnalysisResult = AIAnalysisResult

spec = importlib.util.spec_from_file_location(
    "trendradar.__main__", os.path.join(ROOT, "trendradar/__main__.py")
)
main = importlib.util.module_from_spec(spec)
sys.modules["trendradar.__main__"] = main
spec.loader.exec_module(main)
NewsAnalyzer = main.NewsAnalyzer
"""


class TestAIAnalysisScheduleMode(unittest.TestCase):
    def test_missing_schedule_defaults_to_current_mode(self):
        code = _PREAMBLE + """
ctx = SimpleNamespace(
    config={
        "AI_ANALYSIS": {"ENABLED": True, "MODE": "follow_report"},
        "AI": {"MODEL": "test/model", "API_KEY": "k"},
        "DEBUG": False,
        "BACKGROUND_PULL_ONLY": False,
    },
    get_time=lambda: None,
    source_tier_resolver=object(),
)
fake = SimpleNamespace(ctx=ctx)
result = NewsAnalyzer._run_ai_analysis(
    fake,
    stats=[{"word": "x", "titles": [{"title": "x"}]}],
    rss_items=[],
    mode="current",
    report_type="当前榜单",
    id_to_name={"weibo": "微博"},
    schedule=None,
)
assert result.success is True
assert result.ai_mode == "current"
assert AI_CALLS[-1]["report_mode"] == "current"
"""
        result = _run_in_subprocess(code)
        self.assertEqual(
            result.returncode, 0,
            f"Subprocess failed:\nstdout: {result.stdout}\nstderr: {result.stderr}",
        )

    def test_follow_report_uses_schedule_ai_mode_and_prepares_matching_data(self):
        code = _PREAMBLE + """
ctx = SimpleNamespace(
    config={
        "AI_ANALYSIS": {"ENABLED": True, "MODE": "follow_report"},
        "AI": {"MODEL": "test/model", "API_KEY": "k"},
        "DEBUG": False,
        "BACKGROUND_PULL_ONLY": False,
    },
    get_time=lambda: None,
    source_tier_resolver=object(),
)
prepared = {
    "called": False,
    "mode": None,
}

def prepare(ai_mode, current_results, id_to_name):
    prepared["called"] = True
    prepared["mode"] = ai_mode
    return ([{"word": "daily", "titles": [{"title": "daily"}]}], id_to_name)

fake = SimpleNamespace(ctx=ctx, _prepare_ai_analysis_data=prepare)
schedule = ResolvedSchedule(
    analyze=True,
    report_mode="current",
    ai_mode="daily",
    once_analyze=False,
)
result = NewsAnalyzer._run_ai_analysis(
    fake,
    stats=[{"word": "current", "titles": [{"title": "current"}]}],
    rss_items=[],
    mode="current",
    report_type="当前榜单",
    id_to_name={"weibo": "微博"},
    current_results={"weibo": {}},
    schedule=schedule,
)
assert result.success is True
assert result.ai_mode == "daily"
assert prepared["called"] is True
assert prepared["mode"] == "daily"
assert AI_CALLS[-1]["report_mode"] == "daily"
assert AI_CALLS[-1]["report_type"] == "当日汇总"
assert AI_CALLS[-1]["stats"][0]["word"] == "daily"
"""
        result = _run_in_subprocess(code)
        self.assertEqual(
            result.returncode, 0,
            f"Subprocess failed:\nstdout: {result.stdout}\nstderr: {result.stderr}",
        )


if __name__ == "__main__":
    unittest.main()
