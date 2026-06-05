# coding=utf-8
"""
高热未归类兜底 + 背景表 realtime pull-only 的单元测试。

不联网、不依赖第三方库：按文件路径加载 trendradar.core.frequency / analyzer，
并 stub 掉 trendradar.utils.time（避免 pytz 依赖）。

覆盖：
  - 高热未归类：每条高热未归类标题生成独立 synthetic 组；低热不进；
    Top max_items 截断；统一排在最后；关闭时不产生。
  - strip_background_groups：按前缀剔除背景组，不影响其它组、不改入参。
"""

import importlib.util
import os
import sys
import types
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _ensure_pkg(name, relpath=None):
    """注册（或补全）一个命名空间包。

    relpath 给定时把 __path__ 指向真实目录，避免遮蔽真实子模块——否则共享解释器里
    其它测试（如 test_rss_anthropic_html 导入 trendradar.utils.url）会因空 __path__ 失败。
    """
    real_path = os.path.join(ROOT, relpath) if relpath else None
    if name not in sys.modules:
        m = types.ModuleType(name)
        m.__path__ = [real_path] if real_path else []
        sys.modules[name] = m
    elif real_path and not getattr(sys.modules[name], "__path__", None):
        sys.modules[name].__path__ = [real_path]
    return sys.modules[name]


def _load_file(name, relpath):
    spec = importlib.util.spec_from_file_location(name, os.path.join(ROOT, relpath))
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


_ensure_pkg("trendradar", "trendradar")
_ensure_pkg("trendradar.core", os.path.join("trendradar", "core"))
_ensure_pkg("trendradar.utils", os.path.join("trendradar", "utils"))
# 仅预置 utils.time 的轻量替身（analyzer 只取 DEFAULT_TIMEZONE），避免引入 pytz；
# 其余 trendradar.utils.* 子模块仍可经真实 __path__ 正常解析。
if "trendradar.utils.time" not in sys.modules:
    _t = types.ModuleType("trendradar.utils.time")
    _t.DEFAULT_TIMEZONE = "Asia/Shanghai"
    sys.modules["trendradar.utils.time"] = _t

_freq = _load_file("trendradar.core.frequency", "trendradar/core/frequency.py")
_analyzer = _load_file("trendradar.core.analyzer", "trendradar/core/analyzer.py")

count_word_frequency = _analyzer.count_word_frequency
strip_background_groups = _analyzer.strip_background_groups


def _group(pattern, display, key=None):
    """构造一个 normal-only 词组（mimic load_frequency_words 产出）。"""
    return {
        "required": [],
        "normal": [_freq._parse_word(pattern)],
        "group_key": key or pattern.strip("/"),
        "display_name": display,
        "max_count": 0,
    }


def _title(ranks):
    return {"ranks": ranks, "url": "", "mobileUrl": ""}


class TestHighHeatCatchAll(unittest.TestCase):
    def _run(self, **kw):
        word_groups = [_group("/裁员/", "经济压力")]
        results = {
            "weibo": {
                "某公司大规模裁员": _title([2]),        # 命中 经济压力
                "某地突发爆炸事故": _title([1]),        # 未归类 + 高热 → 兜底
                "明星新剧今日上线": _title([3]),        # 未归类 + 高热 → 兜底
                "本地早高峰交通拥堵": _title([50]),     # 未归类 + 低热 → 丢弃
            }
        }
        stats, _ = count_word_frequency(
            results,
            word_groups,
            filter_words=[],
            id_to_name={"weibo": "微博"},
            title_info=None,
            rank_threshold=5,
            mode="daily",
            global_filters=[],
            quiet=True,
            **kw,
        )
        return stats

    def test_per_title_synthetic_topics(self):
        stats = self._run(catch_all_enabled=True, catch_all_min_rank=5, catch_all_max_items=5)
        words = {s["word"]: s for s in stats}

        # 命中组保留
        self.assertIn("经济压力", words)
        self.assertEqual(words["经济压力"]["count"], 1)

        # 两条高热未归类各成独立 synthetic 组
        synth = [s for s in stats if s["word"].startswith("高热未归类·")]
        self.assertEqual(len(synth), 2)
        synth_titles = {s["titles"][0]["title"] for s in synth}
        self.assertEqual(synth_titles, {"某地突发爆炸事故", "明星新剧今日上线"})
        for s in synth:
            self.assertEqual(s["count"], 1)

        # 低热未归类不进
        self.assertNotIn("高热未归类·本地早高峰交通拥堵", words)

        # synthetic 组排在所有真实组之后（position 远大于真实组）
        real_pos = words["经济压力"]["position"]
        for s in synth:
            self.assertGreater(s["position"], real_pos)
            self.assertGreaterEqual(s["position"], 1000)

    def test_max_items_caps_and_prefers_hottest(self):
        stats = self._run(catch_all_enabled=True, catch_all_min_rank=5, catch_all_max_items=1)
        synth = [s for s in stats if s["word"].startswith("高热未归类·")]
        self.assertEqual(len(synth), 1)
        # 只保留最热（rank 最小）的那条
        self.assertEqual(synth[0]["titles"][0]["title"], "某地突发爆炸事故")

    def test_disabled_produces_no_synthetic(self):
        stats = self._run(catch_all_enabled=False)
        synth = [s for s in stats if s["word"].startswith("高热未归类·")]
        self.assertEqual(synth, [])

    def test_global_filtered_title_not_caught(self):
        # 被 global_filter 排除的标题，即便高热也不应进兜底
        word_groups = [_group("/裁员/", "经济压力")]
        results = {"weibo": {"震惊体某爆炸事故": _title([1])}}
        stats, _ = count_word_frequency(
            results, word_groups, filter_words=[], id_to_name={"weibo": "微博"},
            title_info=None, rank_threshold=5, mode="daily",
            global_filters=["震惊"], quiet=True,
            catch_all_enabled=True, catch_all_min_rank=5, catch_all_max_items=5,
        )
        synth = [s for s in stats if s["word"].startswith("高热未归类·")]
        self.assertEqual(synth, [])


class TestStripBackgroundGroups(unittest.TestCase):
    def test_removes_only_background_prefixed(self):
        stats = [
            {"word": "经济体感与社会压力", "count": 3},
            {"word": "背景-宏观经济", "count": 1},
            {"display_name": "背景-人口财政公共服务", "count": 2},
            {"word": "公共安全与社会失序", "count": 5},
        ]
        out = strip_background_groups(stats, "背景-")
        names = [s.get("word") or s.get("display_name") for s in out]
        self.assertEqual(names, ["经济体感与社会压力", "公共安全与社会失序"])
        # 不修改入参
        self.assertEqual(len(stats), 4)

    def test_empty_or_no_prefix_returns_as_is(self):
        self.assertEqual(strip_background_groups([], "背景-"), [])
        self.assertIsNone(strip_background_groups(None, "背景-"))
        stats = [{"word": "背景-宏观经济"}]
        # 前缀为空 → 原样返回
        self.assertEqual(strip_background_groups(stats, ""), stats)


if __name__ == "__main__":
    unittest.main()
