# coding=utf-8
"""
静态文件验收：新 prompt、source_tiers.yaml、config.yaml 的关键内容。
不依赖第三方库（纯文本断言），保证在任意 Python 下可运行。
"""

import os
import sys
import importlib.util
import types
import unittest

sys.path.insert(0, os.path.dirname(__file__))
import _bootstrap  # noqa: E402

ROOT = _bootstrap.ROOT


def read(relpath):
    with open(os.path.join(ROOT, relpath), "r", encoding="utf-8") as f:
        return f.read()


def load_file(name, relpath):
    spec = importlib.util.spec_from_file_location(name, os.path.join(ROOT, relpath))
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


class TestEnvironmentPromptFile(unittest.TestCase):
    def setUp(self):
        self.text = read("config/ai_environment_report_prompt.txt")

    def test_has_system_and_user_sections(self):
        self.assertIn("[system]", self.text)
        self.assertIn("[user]", self.text)

    def test_injects_evidence_not_raw_titles(self):
        # 注入结构化证据 + 统计骨架
        self.assertIn("{evidence_summary}", self.text)
        self.assertIn("{overview_stats}", self.text)
        self.assertIn("{current_time}", self.text)
        self.assertIn("{language}", self.text)
        # 不得注入 classic 的 raw title 池
        self.assertNotIn("{news_content}", self.text)
        self.assertNotIn("{rss_content}", self.text)

    def test_role_is_monitor_editor_not_intelligence_analyst(self):
        # 用真实 loader 取出 [system] 段，确保 AI 角色不是旧版"高级情报分析师"
        import trendradar.ai.prompt_loader as pl
        system, _ = pl.load_prompt_template("ai_environment_report_prompt.txt", label="AI")
        self.assertIn("信息环境异常监测报告编辑", system)
        # 旧版 classic system 的标志句不应出现在新角色定义中
        self.assertNotIn("你是一名高级情报分析师", system)

    def test_forbids_changing_verification_status(self):
        self.assertIn("verification_status", self.text)
        # 明确约束 sample_titles 不得当事实复述（验收第 4 点）
        self.assertIn("sample_titles", self.text)

    def test_real_prompt_parses_into_system_user(self):
        # 用真实 prompt_loader 解析，确认能拆出非空 system / user
        import trendradar.ai.prompt_loader as pl
        system, user = pl.load_prompt_template("ai_environment_report_prompt.txt", label="AI")
        self.assertTrue(system.strip())
        self.assertTrue(user.strip())
        self.assertIn("{evidence_summary}", user)


class TestSourceTiersYaml(unittest.TestCase):
    def setUp(self):
        self.text = read("config/source_tiers.yaml")

    def test_has_tier_sections(self):
        for key in ["tiers:", "platforms:", "rss_feeds:"]:
            self.assertIn(key, self.text)

    def test_known_platform_tiers_declared(self):
        # 抽查几个关键映射
        self.assertIn("weibo:", self.text)
        self.assertIn("toutiao:", self.text)
        self.assertIn("openai-news:", self.text)
        self.assertIn("bbc-world:", self.text)
        self.assertIn("ruanyifeng:", self.text)


class TestConfigYaml(unittest.TestCase):
    def setUp(self):
        self.text = read("config/config.yaml")
        import yaml
        self.config = yaml.safe_load(self.text)

    def test_dead_top_level_sections_are_absent(self):
        for section in ("display", "notification", "alert", "telegram_attachments"):
            with self.subTest(section=section):
                self.assertNotIn(section, self.config)

    def test_display_mode_and_standalone_translation_scope_are_absent(self):
        self.assertNotIn("display_mode", self.config["report"])
        self.assertNotIn("standalone", self.config["ai_translation"]["scope"])

    def test_environment_prompt_file_configured(self):
        self.assertIn("environment_prompt_file:", self.text)
        self.assertIn("ai_environment_report_prompt.txt", self.text)

    def test_classic_analysis_fields_are_absent(self):
        analysis = self.config["ai_analysis"]
        for field in ("report_style", "prompt_file", "include_standalone"):
            with self.subTest(field=field):
                self.assertNotIn(field, analysis)

    def test_advanced_notification_fields_are_absent(self):
        advanced = self.config["advanced"]
        for field in (
            "max_accounts_per_channel",
            "batch_size",
            "batch_send_interval",
            "feishu_message_separator",
        ):
            with self.subTest(field=field):
                self.assertNotIn(field, advanced)

    def test_anthropic_feeds_use_official_html_fallback(self):
        self.assertIn('id: "anthropic-news-openrss"', self.text)
        self.assertIn('id: "anthropic-research-openrss"', self.text)

        news_start = self.text.index('id: "anthropic-news-openrss"')
        news_block = self.text[news_start:self.text.find("\n\n", news_start)]
        self.assertIn('url: "https://www.anthropic.com/news"', news_block)
        self.assertIn('source_type: "anthropic_html"', news_block)
        self.assertIn('link_prefixes: ["/news/"]', news_block)

        research_start = self.text.index('id: "anthropic-research-openrss"')
        research_block = self.text[research_start:self.text.find("\n\n", research_start)]
        self.assertIn('url: "https://www.anthropic.com/research"', research_block)
        self.assertIn('source_type: "anthropic_html"', research_block)
        self.assertIn('link_prefixes: ["/research/", "/news/"]', research_block)


class TestConfigLoader(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        _bootstrap._ensure_pkg("trendradar")
        _bootstrap._ensure_pkg("trendradar.core")
        _bootstrap._ensure_pkg("trendradar.utils")
        if "trendradar.utils.time" not in sys.modules:
            time_mod = types.ModuleType("trendradar.utils.time")
            time_mod.DEFAULT_TIMEZONE = "Asia/Shanghai"
            sys.modules["trendradar.utils.time"] = time_mod
        if "yaml" not in sys.modules and importlib.util.find_spec("yaml") is None:
            yaml_mod = types.ModuleType("yaml")
            yaml_mod.safe_load = lambda *_args, **_kwargs: {}
            sys.modules["yaml"] = yaml_mod
        cls.loader = load_file("trendradar.core.loader", "trendradar/core/loader.py")

    def test_ai_analysis_loader_has_no_classic_fields(self):
        cfg = self.loader._load_ai_analysis_config(
            {
                "ai_analysis": {
                    "report_style": "classic",
                    "prompt_file": "legacy.txt",
                    "include_standalone": True,
                }
            }
        )
        self.assertNotIn("REPORT_STYLE", cfg)
        self.assertNotIn("PROMPT_FILE", cfg)
        self.assertNotIn("INCLUDE_STANDALONE", cfg)
        self.assertEqual(
            cfg["ENVIRONMENT_PROMPT_FILE"],
            "ai_environment_report_prompt.txt",
        )

    def test_report_and_translation_loaders_have_no_display_compatibility(self):
        report = self.loader._load_report_config(
            {"report": {"display_mode": "platform"}}
        )
        translation = self.loader._load_ai_translation_config(
            {"ai_translation": {"scope": {"standalone": True}}}
        )
        self.assertNotIn("DISPLAY_MODE", report)
        self.assertNotIn("STANDALONE", translation["SCOPE"])

    def test_rss_max_retries_defaults_to_two(self):
        cfg = self.loader._load_rss_config({})
        self.assertEqual(cfg["MAX_RETRIES"], 2)

    def test_rss_max_retries_loads_override(self):
        cfg = self.loader._load_rss_config({"advanced": {"rss": {"max_retries": 4}}})
        self.assertEqual(cfg["MAX_RETRIES"], 4)

    def test_rss_max_retries_invalid_value_falls_back_to_two(self):
        for value in ("bad", -1, None):
            with self.subTest(value=value):
                cfg = self.loader._load_rss_config(
                    {"advanced": {"rss": {"max_retries": value}}}
                )
                self.assertEqual(cfg["MAX_RETRIES"], 2)


class TestMainPipelineSource(unittest.TestCase):
    def test_ai_analysis_runs_when_only_rss_has_content(self):
        text = read("trendradar/__main__.py")
        self.assertIn('if ai_config.get("ENABLED", False) and (stats or rss_items):', text)


if __name__ == "__main__":
    unittest.main()
