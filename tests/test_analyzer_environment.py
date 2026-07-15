# coding=utf-8
"""Environment DR pipeline: structured event protocol and deterministic fallback."""

import datetime
import json
import os
import re
import sys
import unittest

sys.path.insert(0, os.path.dirname(__file__))
import _bootstrap  # noqa: E402

B = _bootstrap.load_all()
EV = B.evidence
T = _bootstrap.make_title
SCHEMA = B.analyzer.ENVIRONMENT_SCHEMA_VERSION


def _time_func():
    return datetime.datetime(2026, 6, 4, 20, 0, 0)


def make_analyzer(**analysis_overrides):
    ai_config = {"MODEL": "test/model", "API_KEY": "k", "TIMEOUT": 10, "MAX_TOKENS": 100}
    analysis_config = {
        "ENABLED": True,
        "REPORT_STYLE": "environment",
        "ENVIRONMENT_PROMPT_FILE": "ai_environment_report_prompt.txt",
        "LANGUAGE": "Chinese",
        "INCLUDE_RSS": True,
        "MAX_NEWS_FOR_ANALYSIS": 200,
        "MAX_OUTPUT_TOKENS": 16000,
        "MAX_EVENTS": 30,
        "BATCH_MAX_EVIDENCE": 12,
    }
    analysis_config.update(analysis_overrides)
    return B.analyzer.AIAnalyzer(ai_config, analysis_config, _time_func, debug=False)


def evidence_id(title, source):
    return EV._evidence_id(T(title, source, 1))


def event(title, summary, analysis, *ids):
    return {
        "title": title,
        "summary": summary,
        "analysis": analysis,
        "evidence_ids": list(ids),
    }


def response(items, overview="今日异常传播主要集中于 D 层，部分存在背景源呼应。", schema=SCHEMA):
    return json.dumps(
        {
            "schema_version": schema,
            "overview": overview,
            "items": [
                {"topic_group": topic, "events": events}
                for topic, events in items.items()
            ],
            "background_notes": [],
        },
        ensure_ascii=False,
    )


SAMPLE_STATS = [
    {"word": "AI前沿模型", "titles": [T("GPT传闻", "微博", 5)]},
    {"word": "某明星瓜", "titles": [T("某事发生", "微博", 3), T("吃瓜", "抖音", 6)]},
    {"word": "财经观察", "titles": [T("财报", "华尔街见闻", 12)]},
]
SAMPLE_RSS = [
    {"word": "AI前沿模型", "titles": [T("OpenAI ships", "OpenAI News", 1)]},
]

GPT_ID = evidence_id("GPT传闻", "微博")
OPENAI_ID = evidence_id("OpenAI ships", "OpenAI News")
STAR_ID = evidence_id("某事发生", "微博")
GOSSIP_ID = evidence_id("吃瓜", "抖音")


def full_response():
    return response(
        {
            "AI前沿模型": [
                event(
                    "OpenAI 新模型相关内容出现跨层传播",
                    "OpenAI News 与微博分别出现新模型相关记录，现有证据只能确认来源之间存在对应传播。",
                    "A 层与 D 层各有一条记录。",
                    GPT_ID,
                    OPENAI_ID,
                )
            ],
            "某明星瓜": [
                event(
                    "某事相关说法进入微博热榜",
                    "标题为『某事发生』的内容进入微博前列，目前只有社交平台记录，不能确认标题主张。",
                    "仅绑定微博 D 层记录。",
                    STAR_ID,
                ),
                event(
                    "吃瓜话题进入抖音热榜",
                    "『吃瓜』这一标题在抖音进入高位，但证据没有提供具体对象或进展。",
                    "仅绑定抖音 D 层记录。",
                    GOSSIP_ID,
                ),
            ],
        }
    )


class TestEnvironmentAssembly(unittest.TestCase):
    def setUp(self):
        self.az = make_analyzer()
        self.captured = []

        def fake_call(user_prompt):
            self.captured.append(user_prompt)
            return full_response()

        self.az._call_ai = fake_call
        self.result = self.az.analyze(
            stats=SAMPLE_STATS,
            rss_stats=SAMPLE_RSS,
            source_tier_resolver=_bootstrap.make_resolver(B),
        )

    def test_structured_result_is_successful(self):
        self.assertTrue(self.result.success, self.result.error)
        self.assertEqual(self.result.report_style, "environment")
        self.assertIn("D 层", self.result.overview)

    def test_events_are_grounded_and_program_labeled(self):
        cross = self.result.cross_layer_verified[0]
        self.assertEqual(cross["verification_status"], EV.LABELS["cross_layer_verified"]["verification_status"])
        self.assertEqual(set(cross["evidence_detail"]["evidence_ids"]), {GPT_ID, OPENAI_ID})
        self.assertTrue(cross["event_id"].startswith("evt_"))
        self.assertNotIn("本组", cross["topic"])

    def test_high_heat_events_keep_fixed_boundary(self):
        self.assertEqual(len(self.result.high_heat_unverified), 2)
        for item in self.result.high_heat_unverified:
            self.assertEqual(item["risk_note"], EV.RISK_NOTE_HIGH_HEAT)
            self.assertEqual(item["factual_boundary"], EV.LABELS["high_heat_unverified"]["factual_boundary"])

    def test_background_is_program_owned(self):
        self.assertIn("财经观察", " ".join(self.result.background_notes))

    def test_prompt_uses_stable_ids_and_no_raw_placeholders(self):
        prompt = self.captured[0]
        self.assertIn("evidence_id=ev_", prompt)
        self.assertNotIn("{evidence_summary}", prompt)
        self.assertNotIn("{news_content}", prompt)


class TestEventReclassification(unittest.TestCase):
    def test_split_events_get_their_own_bucket_and_boundary(self):
        az = make_analyzer()
        az._call_ai = lambda _: response(
            {
                "AI前沿模型": [
                    event("微博传播 GPT 相关说法", "微博出现相关标题。", "单一 D 层。", GPT_ID),
                    event("OpenAI News 收录模型消息", "官方来源出现记录。", "单一 A 层。", OPENAI_ID),
                ],
                "某明星瓜": [
                    event("微博出现某事相关传播", "微博出现相关标题。", "单一 D 层。", STAR_ID),
                    event("抖音出现吃瓜传播", "抖音出现相关标题。", "单一 D 层。", GOSSIP_ID),
                ],
            }
        )
        result = az.analyze(
            stats=SAMPLE_STATS,
            rss_stats=SAMPLE_RSS,
            source_tier_resolver=_bootstrap.make_resolver(B),
        )
        self.assertTrue(result.success, result.error)
        self.assertEqual(result.cross_layer_verified, [])
        self.assertEqual(len(result.silence_gap), 1)
        self.assertEqual(result.silence_gap[0]["factual_boundary"], EV.LABELS["silence_gap"]["factual_boundary"])
        self.assertEqual(len(result.high_heat_unverified), 3)

    def test_overview_stats_are_recomputed_from_split_events(self):
        first_id = evidence_id("低位传播甲", "微博")
        second_id = evidence_id("低位传播乙", "抖音")
        stats = [{
            "word": "同组低位传播",
            "titles": [
                T("低位传播甲", "微博", 11),
                T("低位传播乙", "抖音", 12),
            ],
        }]
        az = make_analyzer()
        az._call_ai = lambda _: response({
            "同组低位传播": [
                event("微博低位传播甲", "微博出现相关标题。", "单一 D 层。", first_id),
                event("抖音低位传播乙", "抖音出现相关标题。", "单一 D 层。", second_id),
            ]
        })

        result = az.analyze(
            stats=stats,
            source_tier_resolver=_bootstrap.make_resolver(B),
        )

        self.assertTrue(result.success, result.error)
        self.assertEqual(result.high_heat_unverified, [])
        self.assertEqual(result.overview_stats["total_items"], 0)
        self.assertEqual(
            result.overview_stats["label_counts"]["high_heat_unverified"], 0
        )
        self.assertEqual(result.overview_stats["background_count"], 2)
        self.assertEqual(result.overview_stats["layer_distribution"]["D"], 2)

    def test_duplicate_evidence_across_groups_is_sent_and_rendered_once(self):
        duplicate_id = evidence_id("重复命中标题", "微博")
        stats = [
            {"word": "先命中组", "titles": [T("重复命中标题", "微博", 1)]},
            {"word": "后命中组", "titles": [T("重复命中标题", "微博", 1)]},
        ]
        for batch_size in (12, 1):
            with self.subTest(batch_size=batch_size):
                az = make_analyzer(BATCH_MAX_EVIDENCE=batch_size)
                prompts = []

                def fake_call(prompt):
                    prompts.append(prompt)
                    return response({
                        "先命中组": [
                            event(
                                "重复标题只生成一个事件",
                                "微博出现相关标题。",
                                "单一 D 层。",
                                duplicate_id,
                            )
                        ]
                    })

                az._call_ai = fake_call
                result = az.analyze(
                    stats=stats,
                    source_tier_resolver=_bootstrap.make_resolver(B),
                )

                self.assertTrue(result.success, result.error)
                self.assertEqual(len(prompts), 1)
                self.assertIn("先命中组", prompts[0])
                self.assertNotIn("议题名: 后命中组", prompts[0])
                self.assertEqual(len(result.high_heat_unverified), 1)
                self.assertEqual(
                    result.high_heat_unverified[0]["topic"],
                    "重复标题只生成一个事件",
                )


class TestEnvironmentFailures(unittest.TestCase):
    def test_call_failure_is_not_scheduler_success_but_keeps_event_fallback(self):
        az = make_analyzer()
        az._call_ai = lambda _: (_ for _ in ()).throw(RuntimeError("network down"))
        result = az.analyze(
            stats=SAMPLE_STATS,
            rss_stats=SAMPLE_RSS,
            source_tier_resolver=_bootstrap.make_resolver(B),
        )
        self.assertFalse(result.success)
        self.assertIn("批次调用失败", result.error)
        all_items = result.high_heat_unverified + result.silence_gap
        self.assertTrue(all(item.get("event_id") for item in all_items))
        self.assertNotIn("AI前沿模型", [item["topic"] for item in all_items])

    def test_bad_json_and_schema_mismatch_are_blocking(self):
        for payload in ("not json", response({}, schema="old-schema")):
            az = make_analyzer()
            az._call_ai = lambda _, value=payload: value
            result = az.analyze(
                stats=[{"word": "X", "titles": [T("a", "微博", 1)]}],
                source_tier_resolver=_bootstrap.make_resolver(B),
            )
            self.assertFalse(result.success)
            self.assertTrue(result.error)

    def test_markdown_wrapped_json_is_rejected(self):
        az = make_analyzer()
        az._call_ai = lambda _: "```json\n" + response({"X": [event("a", "", "", evidence_id("a", "微博"))]}) + "\n```"
        result = az.analyze(
            stats=[{"word": "X", "titles": [T("a", "微博", 1)]}],
            source_tier_resolver=_bootstrap.make_resolver(B),
        )
        self.assertFalse(result.success)
        self.assertIn("JSON 解析错误", result.error)

    def test_max_tokens_is_rejected_and_metadata_preserved(self):
        az = make_analyzer(BATCH_MAX_EVIDENCE=1)

        def truncated(_):
            az.client.last_response_metadata = {
                "finish_reason": "MAX_TOKENS",
                "usage": {"completion_tokens": 16000},
                "model": "gemini-3.5-flash",
            }
            return '{"schema_version":"environment-events-v1"'

        az._call_ai = truncated
        result = az.analyze(
            stats=[{"word": "X", "titles": [T("a", "微博", 1)]}],
            source_tier_resolver=_bootstrap.make_resolver(B),
        )
        self.assertFalse(result.success)
        self.assertIn("MAX_TOKENS", result.error)
        self.assertEqual(result.ai_response_metadata[0]["usage"]["completion_tokens"], 16000)
        self.assertTrue(result.ai_response_metadata[0]["discarded"])

    def test_missing_evidence_coverage_is_blocking_and_falls_back(self):
        az = make_analyzer()
        az._call_ai = lambda _: response(
            {
                "某明星瓜": [
                    event("只返回一条", "一条", "单一 D 层", STAR_ID),
                ]
            }
        )
        stats = [{"word": "某明星瓜", "titles": [T("某事发生", "微博", 3), T("吃瓜", "抖音", 6)]}]
        result = az.analyze(stats=stats, source_tier_resolver=_bootstrap.make_resolver(B))
        self.assertFalse(result.success)
        self.assertIn("evidence 覆盖不完整", result.error)
        self.assertEqual(len(result.high_heat_unverified), 2)
        self.assertTrue(any("吃瓜" in item["topic"] for item in result.high_heat_unverified))


class TestBatchingAndLimits(unittest.TestCase):
    def test_batches_merge_and_cover_all_evidence(self):
        az = make_analyzer(BATCH_MAX_EVIDENCE=1)
        calls = []

        def one_evidence(prompt):
            calls.append(prompt)
            topic = re.search(r"议题「([^」]+)」", prompt).group(1)
            ev_id = re.search(r"evidence_id=(ev_[0-9a-f]+)", prompt).group(1)
            return response({topic: [event(f"事件 {len(calls)}", "摘要", "单一来源", ev_id)]})

        az._call_ai = one_evidence
        result = az.analyze(
            stats=SAMPLE_STATS,
            rss_stats=SAMPLE_RSS,
            source_tier_resolver=_bootstrap.make_resolver(B),
        )
        self.assertTrue(result.success, result.error)
        self.assertEqual(len(calls), 4)
        self.assertEqual(len(result.ai_response_metadata), 4)

    def test_group_limit_only_limits_prompt_not_program_events(self):
        az = make_analyzer(MAX_NEWS_FOR_ANALYSIS=1)
        captured = []

        def fake_call(prompt):
            captured.append(prompt)
            return response({"A议题": [event("A事件", "摘要", "D 层", evidence_id("a", "微博"))]})

        az._call_ai = fake_call
        stats = [
            {"word": "A议题", "titles": [T("a", "微博", 1)]},
            {"word": "B议题", "titles": [T("b", "抖音", 2)]},
        ]
        result = az.analyze(stats=stats, source_tier_resolver=_bootstrap.make_resolver(B))
        self.assertTrue(result.success, result.error)
        self.assertIn("议题「A议题」", captured[0])
        self.assertNotIn("议题「B议题」", captured[0])
        self.assertEqual(len(result.high_heat_unverified), 2)

    def test_include_rss_false_excludes_rss_evidence(self):
        az = make_analyzer(INCLUDE_RSS=False)
        az._call_ai = lambda _: response(
            {"AI前沿模型": [event("微博模型传播", "摘要", "D 层", GPT_ID)]}
        )
        result = az.analyze(
            stats=[{"word": "AI前沿模型", "titles": [T("GPT传闻", "微博", 5)]}],
            rss_stats=SAMPLE_RSS,
            source_tier_resolver=_bootstrap.make_resolver(B),
        )
        self.assertTrue(result.success, result.error)
        self.assertEqual(result.rss_count, 0)
        self.assertEqual(result.cross_layer_verified, [])


class TestClassicDeprecated(unittest.TestCase):
    def test_classic_config_is_normalized_to_environment(self):
        az = make_analyzer(REPORT_STYLE="classic")
        ev_id = evidence_id("a", "微博")
        az._call_ai = lambda _: response({"X": [event("a传播", "摘要", "D 层", ev_id)]})
        result = az.analyze(
            stats=[{"word": "X", "titles": [T("a", "微博", 2)]}],
            source_tier_resolver=_bootstrap.make_resolver(B),
        )
        self.assertEqual(result.report_style, "environment")
        self.assertEqual(az.report_style, "environment")


class TestProviderSpecificConfig(unittest.TestCase):
    def _client_config(self, model):
        analyzer = B.analyzer.AIAnalyzer(
            {"MODEL": model, "API_KEY": "k"},
            {
                "ENVIRONMENT_PROMPT_FILE": "ai_environment_report_prompt.txt",
                "MAX_OUTPUT_TOKENS": 16000,
            },
            _time_func,
        )
        return analyzer.client.config

    def test_low_reasoning_is_automatic_only_for_gemini_3(self):
        gemini = self._client_config("gemini/gemini-3.5-flash")
        deepseek = self._client_config("deepseek/deepseek-v4-flash")
        self.assertEqual(gemini["EXTRA_PARAMS"]["reasoning_effort"], "low")
        self.assertIsNone(gemini["TEMPERATURE"])
        self.assertNotIn("reasoning_effort", deepseek["EXTRA_PARAMS"])


if __name__ == "__main__":
    unittest.main()
