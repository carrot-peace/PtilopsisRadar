# coding=utf-8
"""Tests for the DR dispatch pipeline."""

from __future__ import annotations

import dataclasses
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from trendradar.ai.analyzer import AIAnalysisResult
from trendradar.dr.dispatch_executor import (
    DRMemoryDispatchSink,
    execute_dr_dispatch_plan,
)
from trendradar.dr.dispatch_mode import (
    DR_DISPATCH_ARTIFACT,
    DR_DISPATCH_LIVE,
    DR_DISPATCH_OFF,
    resolve_dr_dispatch_mode,
)
from trendradar.dr.dispatch_plan import (
    DRDispatchMessage,
    build_dr_dispatch_plan,
)
from trendradar.dr.formatter import (
    DR_FALLBACK_TEXT,
    _telegram_visible_length,
    render_dr_telegram_text,
    select_dr_digest_topics,
)
from trendradar.dr.telegram_env import (
    build_dr_telegram_sink_config_from_env,
    build_dr_telegram_sink_from_env,
    dr_telegram_send_enabled,
)
from trendradar.dr.telegram_sink import (
    DRTelegramSink,
)
from trendradar.telegram.recipients import ReaderRecipientProvider
from trendradar.telegram.transport import TelegramHTTPResponse


FAKE_TOKEN = "FAKE-DR-TOKEN-000:abc"
FAKE_CHAT = "fake-dr-chat"


def _ai_result(**overrides) -> AIAnalysisResult:
    result = AIAnalysisResult(
        report_style="environment",
        success=True,
        overview="今日 AI Brief 概览。",
        cross_layer_verified=[
            {
                "topic": "Topic A",
                "source_layers": "A/B",
                "highest_heat": "#1",
                "summary": "Topic A summary",
                "source_links": ["https://example.test/a"],
            }
        ],
        high_heat_unverified=[
            {
                "topic": "Topic B",
                "source_layers": "D",
                "highest_heat": "#2",
                "summary": "Topic B summary with https://example.test/link",
            }
        ],
        chinese_only_hot=[
            {
                "topic": "Topic A!",
                "source_layers": "D",
                "highest_heat": "#3",
                "summary": "Duplicate topic should be removed",
            }
        ],
    )
    for key, value in overrides.items():
        setattr(result, key, value)
    return result


class TestDRFormatter(unittest.TestCase):
    def test_ai_overview_rendered(self) -> None:
        text = render_dr_telegram_text(_ai_result(), date="2026-06-18")
        self.assertIn("Ptilopsis Radar｜DR", text)
        self.assertIn("<b>导读</b>", text)
        self.assertIn("今日 AI Brief 概览", text)

    def test_topics_selected_and_deduped(self) -> None:
        topics = select_dr_digest_topics(_ai_result())
        self.assertEqual([t["topic"] for t in topics], ["Topic A", "Topic B"])

    def test_no_ai_fallback(self) -> None:
        text = render_dr_telegram_text(None, date="2026-06-18")
        self.assertIn(DR_FALLBACK_TEXT, text)
        self.assertIn("完整报告：见随附 HTML", text)

    def test_failed_ai_fallback(self) -> None:
        failed = AIAnalysisResult(report_style="environment", success=False, error="x")
        text = render_dr_telegram_text(failed, date="2026-06-18")
        self.assertIn(DR_FALLBACK_TEXT, text)

    def test_non_environment_ai_fallback(self) -> None:
        unsupported = _ai_result(report_style="unsupported")
        text = render_dr_telegram_text(unsupported, date="2026-06-18")
        self.assertIn(DR_FALLBACK_TEXT, text)
        self.assertEqual(select_dr_digest_topics(unsupported), [])

    def test_failed_ai_keeps_analyzer_event_fallbacks(self) -> None:
        failed = _ai_result(success=False, overview="不应展示的截断概述")
        text = render_dr_telegram_text(failed, date="2026-06-18")
        self.assertIn(DR_FALLBACK_TEXT, text)
        self.assertIn("Topic A", text)
        self.assertIn("Topic B", text)
        self.assertNotIn("不应展示的截断概述", text)

    def test_intentionally_skipped_analysis_is_not_reported_as_ai_failure(self) -> None:
        skipped = AIAnalysisResult(
            report_style="environment", success=False, skipped=True
        )
        text = render_dr_telegram_text(skipped, date="2026-06-18")
        self.assertIn("本轮未识别达到异常阈值的事件", text)
        self.assertNotIn(DR_FALLBACK_TEXT, text)

    def test_text_omits_urls_and_decision(self) -> None:
        text = render_dr_telegram_text(_ai_result(), date="2026-06-18")
        self.assertNotIn("https://", text)
        self.assertNotIn("Decision", text)
        self.assertNotIn("source_links", text)

    def test_missing_ai_brief_uses_program_counts(self) -> None:
        result = _ai_result(
            overview="",
            overview_stats={
                "label_counts": {
                    "cross_layer_verified": 0,
                    "high_heat_unverified": 2,
                    "chinese_only_hot": 1,
                    "silence_gap": 1,
                    "sentiment_heavy": 1,
                },
                "background_count": 3,
            },
        )
        text = render_dr_telegram_text(result, date="2026-06-18")
        self.assertIn("今日识别 3 个异常信号", text)
        self.assertIn("1 个社交平台单点高热", text)
        self.assertIn(DR_FALLBACK_TEXT, text)

    def test_noise_is_filtered_and_internal_prefix_is_hidden(self) -> None:
        result = _ai_result(
            cross_layer_verified=[],
            high_heat_unverified=[
                {
                    "topic": "高热未归类·BLG战胜HLE晋级MSI决赛",
                    "summary": "电竞赛果讨论",
                    "source_layers": "D",
                    "highest_heat": "微博 第1名",
                },
                {
                    "topic": "高热未归类·某地发布防汛红色预警",
                    "summary": "关于防汛预警的传播进入平台高位",
                    "source_layers": "D",
                    "highest_heat": "微博 第2名",
                },
                {"topic": "爱豆粉丝见面会", "summary": "娱乐活动传播"},
                {"topic": "哈兰德赛后发言", "summary": "体育赛后传播"},
            ],
            chinese_only_hot=[],
        )
        text = render_dr_telegram_text(result, date="2026-06-18")
        self.assertNotIn("BLG", text)
        self.assertNotIn("高热未归类", text)
        self.assertIn("某地发布防汛红色预警", text)
        self.assertNotIn("爱豆", text)
        self.assertNotIn("哈兰德", text)
        self.assertNotIn("high_heat_unverified", text)
        self.assertNotIn("highest_heat", text)

    def test_near_duplicate_topics_are_collapsed(self) -> None:
        result = _ai_result(
            cross_layer_verified=[],
            high_heat_unverified=[
                {"topic": "某地暴雨红色预警", "summary": "a"},
                {"topic": "某地暴雨红色预警最新消息", "summary": "b"},
            ],
            chinese_only_hot=[],
        )
        topics = select_dr_digest_topics(result)
        self.assertEqual([t["topic"] for t in topics], ["某地暴雨红色预警"])

    def test_missing_ai_summary_falls_back_to_events_not_topic_group(self) -> None:
        result = _ai_result(
            cross_layer_verified=[],
            high_heat_unverified=[{
                "topic": "公共安全与社会失序",
                "summary": "",
                "highest_heat": "今日头条 第1名",
                "evidence_detail": {
                    "sample_titles": [
                        {"title": "海南陵水失联女生已找到"},
                        {"title": "河北宽城多个小区被淹"},
                    ]
                },
            }],
            chinese_only_hot=[],
        )
        topics = select_dr_digest_topics(result)
        self.assertEqual(
            [topic["topic"] for topic in topics],
            ["海南陵水失联女生已找到", "河北宽城多个小区被淹"],
        )
        self.assertNotIn("本组", " ".join(topic["summary"] for topic in topics))

    def test_analysis_is_never_published_as_an_event_summary(self) -> None:
        result = _ai_result(
            cross_layer_verified=[],
            high_heat_unverified=[{
                "topic": "宽泛内部组名",
                "summary": "",
                "analysis": "单一 D 层来源，无上游来源呼应。",
                "evidence_detail": {
                    "sample_titles": [{"title": "某地发布暴雨红色预警"}]
                },
            }],
            chinese_only_hot=[],
        )
        topics = select_dr_digest_topics(result)
        self.assertEqual(topics[0]["topic"], "某地发布暴雨红色预警")
        self.assertNotIn("单一 D 层来源", topics[0]["summary"])

    def test_telegram_output_has_a_hard_visible_character_limit(self) -> None:
        items = []
        for index in range(10):
            marker = chr(0x4E00 + index)
            items.append({
                "topic": f"事件{index}" + marker * 500 + "&" * 100,
                "summary": "详细摘要" * 300,
                "highest_heat": "平台排名" * 100,
                "verification_status": "高热待核实",
            })
        result = _ai_result(
            overview="盘面导读" * 500,
            cross_layer_verified=[],
            high_heat_unverified=items,
            chinese_only_hot=[],
        )

        text = render_dr_telegram_text(
            result, date="2026-06-18", max_items=999
        )

        self.assertLessEqual(_telegram_visible_length(text), 4096)
        self.assertEqual(text.count("<b>"), text.count("</b>"))
        self.assertLessEqual(len(select_dr_digest_topics(result, max_items=999)), 5)

    def test_event_status_wins_over_originating_bucket(self) -> None:
        result = _ai_result(
            cross_layer_verified=[{
                "topic": "只有社交层证据的事件",
                "summary": "相关标题进入平台高位，暂无上游来源呼应。",
                "verification_status": "高热待核实",
                "highest_heat": "微博 第1名",
            }],
            high_heat_unverified=[],
            chinese_only_hot=[],
        )
        topics = select_dr_digest_topics(result)
        self.assertEqual(topics[0]["status_label"], "单点高热，来源待补")
        text = render_dr_telegram_text(result, date="2026-06-18")
        self.assertIn("单点高热，来源待补", text)
        self.assertNotIn("多层来源呼应", text)

    def test_program_brief_counts_events_by_status_not_bucket(self) -> None:
        result = _ai_result(
            overview="",
            cross_layer_verified=[{
                "topic": "只有社交层证据的事件",
                "summary": "相关标题进入平台高位。",
                "verification_status": "高热待核实",
            }],
            high_heat_unverified=[],
            chinese_only_hot=[],
        )
        text = render_dr_telegram_text(result, date="2026-06-18")
        self.assertIn("1 个社交平台单点高热", text)
        self.assertNotIn("1 个多层来源呼应", text)


class TestDRPlanExecutor(unittest.TestCase):
    def test_missing_html_blocks_plan(self) -> None:
        plan = build_dr_dispatch_plan(
            text="body", html_path="", run_label="r", date="2026-06-18"
        )
        self.assertFalse(plan.should_dispatch)
        self.assertEqual(plan.reason, "missing_html")

    def test_empty_text_blocks_plan(self) -> None:
        plan = build_dr_dispatch_plan(
            text=" ", html_path="daily.html", run_label="r", date="2026-06-18"
        )
        self.assertFalse(plan.should_dispatch)
        self.assertEqual(plan.reason, "empty_text")

    def test_ready_plan(self) -> None:
        plan = build_dr_dispatch_plan(
            text="body", html_path="daily.html", run_label="r", date="2026-06-18"
        )
        self.assertTrue(plan.should_dispatch)
        self.assertEqual(plan.reason, "ready")
        self.assertEqual(plan.messages[0].format, "telegram_html")

    def test_frozen_message(self) -> None:
        msg = DRDispatchMessage(
            text="x", format="telegram_html", run_label="r",
            date="2026-06-18", html_path="daily.html",
        )
        with self.assertRaises(dataclasses.FrozenInstanceError):
            msg.text = "y"  # type: ignore[misc]

    def test_executor_artifact_mode_no_sink(self) -> None:
        plan = build_dr_dispatch_plan(
            text="body", html_path="daily.html", run_label="r", date="2026-06-18"
        )
        result = execute_dr_dispatch_plan(plan, sink=None)
        self.assertFalse(result.attempted)
        self.assertEqual(result.reason, "no_sink")

    def test_executor_memory_sink_accepts(self) -> None:
        plan = build_dr_dispatch_plan(
            text="body", html_path="daily.html", run_label="r", date="2026-06-18"
        )
        sink = DRMemoryDispatchSink()
        result = execute_dr_dispatch_plan(plan, sink=sink)
        self.assertTrue(result.attempted)
        self.assertEqual(result.accepted_count, 1)
        self.assertEqual(len(sink.submitted_messages), 1)

    def test_executor_transport_failure_receipt(self) -> None:
        class BadSink:
            def submit(self, message, *, message_index):
                raise TimeoutError("boom")

        plan = build_dr_dispatch_plan(
            text="body", html_path="daily.html", run_label="r", date="2026-06-18"
        )
        result = execute_dr_dispatch_plan(plan, sink=BadSink())
        self.assertEqual(result.receipts[0].status, "failed_transport")


class TestDREnvAndSink(unittest.TestCase):
    def _env(self, **overrides: str) -> dict[str, str]:
        env = {
            "PTILOPSIS_DR_TELEGRAM_SEND": "1",
            "TELEGRAM_BOT_TOKEN": FAKE_TOKEN,
            "TELEGRAM_OWNER_CHAT_IDS": FAKE_CHAT,
        }
        env.update(overrides)
        return env

    def test_mode_default_off(self) -> None:
        self.assertEqual(resolve_dr_dispatch_mode({}), DR_DISPATCH_OFF)

    def test_modes(self) -> None:
        self.assertEqual(
            resolve_dr_dispatch_mode({"PTILOPSIS_DR_DISPATCH_MODE": "artifact"}),
            DR_DISPATCH_ARTIFACT,
        )
        self.assertEqual(
            resolve_dr_dispatch_mode({"PTILOPSIS_DR_DISPATCH_MODE": "live"}),
            DR_DISPATCH_LIVE,
        )

    def test_send_gate_exact_one(self) -> None:
        self.assertTrue(dr_telegram_send_enabled({"PTILOPSIS_DR_TELEGRAM_SEND": "1"}))
        self.assertFalse(dr_telegram_send_enabled({"PTILOPSIS_DR_TELEGRAM_SEND": " 1 "}))

    def test_missing_credentials_raise_when_enabled(self) -> None:
        for key in ("TELEGRAM_BOT_TOKEN", "TELEGRAM_OWNER_CHAT_IDS"):
            with self.subTest(key=key):
                env = self._env()
                del env[key]
                with self.assertRaisesRegex(ValueError, key):
                    build_dr_telegram_sink_config_from_env(env)

    def test_legacy_pipeline_credentials_are_not_fallbacks(self) -> None:
        with self.assertRaisesRegex(ValueError, "TELEGRAM_BOT_TOKEN"):
            build_dr_telegram_sink_config_from_env(
                {
                    "PTILOPSIS_DR_TELEGRAM_SEND": "1",
                    "PTILOPSIS_DR_TELEGRAM_BOT_TOKEN": "legacy-token",
                    "PTILOPSIS_DR_TELEGRAM_CHAT_ID": "legacy-chat",
                }
            )

    def test_disabled_returns_none(self) -> None:
        self.assertIsNone(build_dr_telegram_sink_config_from_env({}))
        self.assertIsNone(build_dr_telegram_sink_from_env({}))

    def test_empty_optional_env_values_use_safe_defaults(self) -> None:
        config = build_dr_telegram_sink_config_from_env(
            self._env(
                TELEGRAM_TIMEOUT_SECONDS="",
                PTILOPSIS_DR_TELEGRAM_ATTACH_HTML="",
            )
        )
        assert config is not None
        self.assertEqual(config.timeout_seconds, 10.0)
        self.assertTrue(config.attach_html)

    def test_canonical_transport_and_owner_options(self) -> None:
        config = build_dr_telegram_sink_config_from_env(
            self._env(
                TELEGRAM_API_BASE_URL="https://telegram.test/",
                TELEGRAM_TIMEOUT_SECONDS="7.5",
                TELEGRAM_OWNER_CHAT_IDS="one,two,one",
            )
        )
        assert config is not None
        self.assertEqual(config.api_base_url, "https://telegram.test/")
        self.assertEqual(config.timeout_seconds, 7.5)
        self.assertEqual(
            [target.chat_id for target in config.recipients.get_targets()],
            ["one", "two"],
        )

    def test_sink_sends_text_and_document(self) -> None:
        class FakeClient:
            def __init__(self):
                self.json_payloads = []
                self.multipart_payloads = []

            def post_json(self, url, payload, *, timeout_seconds):
                self.json_payloads.append((url, payload))
                return TelegramHTTPResponse(200, '{"ok": true}')

            def post_multipart(
                self,
                url,
                *,
                fields,
                file_field,
                file_path,
                timeout_seconds,
                content_type=None,
            ):
                self.multipart_payloads.append(
                    (url, fields, file_field, file_path, content_type)
                )
                return TelegramHTTPResponse(200, '{"ok": true}')

        with tempfile.TemporaryDirectory() as td:
            html_path = Path(td) / "full.html"
            html_path.write_text("<html>DR</html>", encoding="utf-8")
            config = build_dr_telegram_sink_config_from_env(self._env())
            assert config is not None
            fake = FakeClient()
            sink = DRTelegramSink(config=config, http_client=fake)
            receipt = sink.submit(
                DRDispatchMessage(
                    text="body",
                    format="telegram_html",
                    run_label="r",
                    date="2026-06-18",
                    html_path=str(html_path),
                    attach_html=True,
                ),
                message_index=0,
            )
        self.assertTrue(receipt.accepted)
        self.assertTrue(receipt.text_accepted)
        self.assertTrue(receipt.document_accepted)
        self.assertEqual(len(fake.json_payloads), 1)
        self.assertEqual(len(fake.multipart_payloads), 1)
        self.assertEqual(fake.json_payloads[0][1]["chat_id"], FAKE_CHAT)
        self.assertEqual(fake.json_payloads[0][1]["parse_mode"], "HTML")
        self.assertEqual(fake.multipart_payloads[0][1]["caption"], "DR HTML")
        self.assertEqual(
            fake.multipart_payloads[0][4],
            "text/html; charset=utf-8",
        )

    def test_document_failure_keeps_text_accepted(self) -> None:
        class FakeClient:
            def post_json(self, url, payload, *, timeout_seconds):
                return TelegramHTTPResponse(200, '{"ok": true}')

            def post_multipart(
                self,
                url,
                *,
                fields,
                file_field,
                file_path,
                timeout_seconds,
                content_type=None,
            ):
                return TelegramHTTPResponse(400, '{"ok": false}')

        with tempfile.TemporaryDirectory() as td:
            html_path = Path(td) / "full.html"
            html_path.write_text("<html>DR</html>", encoding="utf-8")
            config = build_dr_telegram_sink_config_from_env(self._env())
            assert config is not None
            receipt = DRTelegramSink(config=config, http_client=FakeClient()).submit(
                DRDispatchMessage(
                    text="body",
                    format="telegram_html",
                    run_label="r",
                    date="2026-06-18",
                    html_path=str(html_path),
                    attach_html=True,
                ),
                message_index=0,
            )
        self.assertTrue(receipt.accepted)
        self.assertEqual(receipt.status, "accepted_partial")
        self.assertFalse(receipt.document_accepted)

    def test_partial_fanout_attempts_later_recipients(self) -> None:
        class FakeClient:
            def __init__(self):
                self.chat_ids = []
                self.responses = [
                    TelegramHTTPResponse(200, '{"ok": true}'),
                    TelegramHTTPResponse(500, '{"ok": false}'),
                ]

            def post_json(self, url, payload, *, timeout_seconds):
                del url, timeout_seconds
                self.chat_ids.append(payload["chat_id"])
                return self.responses.pop(0)

        config = build_dr_telegram_sink_config_from_env(self._env())
        assert config is not None
        config = dataclasses.replace(
            config,
            recipients=ReaderRecipientProvider(("owner", "subscriber")),
            attach_html=False,
        )
        fake = FakeClient()

        receipt = DRTelegramSink(config=config, http_client=fake).submit(
            DRDispatchMessage(
                text="body",
                format="telegram_html",
                run_label="r",
                date="2026-06-18",
                html_path="unused.html",
                attach_html=False,
            ),
            message_index=0,
        )

        self.assertEqual(fake.chat_ids, ["owner", "subscriber"])
        self.assertTrue(receipt.accepted)
        self.assertTrue(receipt.text_accepted)
        self.assertEqual(receipt.status, "accepted_partial")
        self.assertIn("recipients=2,text_ok=1,text_failed=1", receipt.detail)


class TestDRSourceBoundaries(unittest.TestCase):
    def test_dr_modules_do_not_import_cr_telegram_or_notification(self) -> None:
        root = Path(__file__).resolve().parent.parent
        for path in (root / "trendradar" / "dr").glob("*.py"):
            text = path.read_text(encoding="utf-8")
            self.assertNotIn("trendradar.cr.telegram", text)
            self.assertNotIn("trendradar.notification", text)
            self.assertNotIn("send_to_telegram", text)
            self.assertNotIn("dispatch_all", text)

    def test_main_has_dr_hook_but_no_legacy_sender_call(self) -> None:
        root = Path(__file__).resolve().parent.parent
        text = (root / "trendradar" / "__main__.py").read_text(encoding="utf-8")
        self.assertIn("_run_dr_dispatch_hook", text)
        self.assertNotIn("send_to_telegram(", text)
        self.assertNotIn("dispatch_all(", text)


if __name__ == "__main__":
    unittest.main()
