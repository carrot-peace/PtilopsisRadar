# coding=utf-8
"""
Tests for CR Telegram env sink factory (PR9o).

No real network calls.  No real tokens.  No real chat IDs.
No environment mutation except via ``patch.dict`` where safe.
"""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from trendradar.cr.telegram_env import (
    build_cr_telegram_sink_config_from_env,
    build_cr_telegram_sink_from_env,
    cr_telegram_send_enabled,
)
from trendradar.cr.telegram_sink import CRTelegramSink
from trendradar.telegram.transport import TelegramHTTPResponse

# Fake values that do NOT match real Telegram token patterns.
FAKE_TOKEN = "FAKE-TOKEN-000:aaaabbbbcccc"
FAKE_CHAT_ID = "fake-chat-42"


# ---------------------------------------------------------------------------
# Test Group A — Enable flag
# ---------------------------------------------------------------------------


class TestTelegramSendEnabled(unittest.TestCase):
    """Group A: enable flag semantics."""

    def test_missing_key_is_disabled(self) -> None:
        self.assertFalse(cr_telegram_send_enabled({}))

    def test_value_zero_is_disabled(self) -> None:
        self.assertFalse(cr_telegram_send_enabled({"PTILOPSIS_CR_TELEGRAM_SEND": "0"}))

    def test_value_false_is_disabled(self) -> None:
        self.assertFalse(
            cr_telegram_send_enabled({"PTILOPSIS_CR_TELEGRAM_SEND": "false"})
        )

    def test_value_one_is_enabled(self) -> None:
        self.assertTrue(
            cr_telegram_send_enabled({"PTILOPSIS_CR_TELEGRAM_SEND": "1"})
        )

    def test_padded_one_is_disabled(self) -> None:
        """Strict: only exact raw value '1' enables.  No stripping."""
        self.assertFalse(
            cr_telegram_send_enabled({"PTILOPSIS_CR_TELEGRAM_SEND": " 1 "})
        )

    def test_value_two_is_disabled(self) -> None:
        self.assertFalse(
            cr_telegram_send_enabled({"PTILOPSIS_CR_TELEGRAM_SEND": "2"})
        )


# ---------------------------------------------------------------------------
# Test Group B — Disabled config/sink
# ---------------------------------------------------------------------------


class TestDisabledReturnsNone(unittest.TestCase):
    """Group B: disabled env returns None, credentials irrelevant."""

    def test_disabled_env_returns_config_none(self) -> None:
        env = {"PTILOPSIS_CR_TELEGRAM_SEND": "0"}
        self.assertIsNone(build_cr_telegram_sink_config_from_env(env))

    def test_disabled_env_returns_sink_none(self) -> None:
        env = {"PTILOPSIS_CR_TELEGRAM_SEND": "0"}
        self.assertIsNone(build_cr_telegram_sink_from_env(env))

    def test_missing_credentials_do_not_matter_when_disabled(self) -> None:
        """No ValueError when disabled, even with empty env."""
        self.assertIsNone(build_cr_telegram_sink_config_from_env({}))
        self.assertIsNone(build_cr_telegram_sink_from_env({}))


# ---------------------------------------------------------------------------
# Test Group C — Required credentials when enabled
# ---------------------------------------------------------------------------


class TestRequiredCredentials(unittest.TestCase):
    """Group C: missing/blank required fields raise ValueError."""

    def _enabled_env(self, **overrides: str) -> dict[str, str]:
        base = {
            "PTILOPSIS_CR_TELEGRAM_SEND": "1",
            "PTILOPSIS_CR_TELEGRAM_BOT_TOKEN": FAKE_TOKEN,
            "PTILOPSIS_CR_TELEGRAM_CHAT_ID": FAKE_CHAT_ID,
        }
        base.update(overrides)
        return base

    def test_missing_token_raises(self) -> None:
        env = self._enabled_env()
        del env["PTILOPSIS_CR_TELEGRAM_BOT_TOKEN"]
        with self.assertRaises(ValueError) as ctx:
            build_cr_telegram_sink_config_from_env(env)
        self.assertIn("PTILOPSIS_CR_TELEGRAM_BOT_TOKEN", str(ctx.exception))

    def test_blank_token_raises(self) -> None:
        env = self._enabled_env(PTILOPSIS_CR_TELEGRAM_BOT_TOKEN="   ")
        with self.assertRaises(ValueError) as ctx:
            build_cr_telegram_sink_config_from_env(env)
        self.assertIn("PTILOPSIS_CR_TELEGRAM_BOT_TOKEN", str(ctx.exception))

    def test_missing_chat_id_raises(self) -> None:
        env = self._enabled_env()
        del env["PTILOPSIS_CR_TELEGRAM_CHAT_ID"]
        with self.assertRaises(ValueError) as ctx:
            build_cr_telegram_sink_config_from_env(env)
        self.assertIn("PTILOPSIS_CR_TELEGRAM_CHAT_ID", str(ctx.exception))

    def test_blank_chat_id_raises(self) -> None:
        env = self._enabled_env(PTILOPSIS_CR_TELEGRAM_CHAT_ID="   ")
        with self.assertRaises(ValueError) as ctx:
            build_cr_telegram_sink_config_from_env(env)
        self.assertIn("PTILOPSIS_CR_TELEGRAM_CHAT_ID", str(ctx.exception))

    def test_error_message_does_not_include_token(self) -> None:
        env = self._enabled_env()
        del env["PTILOPSIS_CR_TELEGRAM_BOT_TOKEN"]
        with self.assertRaises(ValueError) as ctx:
            build_cr_telegram_sink_config_from_env(env)
        self.assertNotIn(FAKE_TOKEN, str(ctx.exception))

    def test_error_message_does_not_include_chat_id(self) -> None:
        env = self._enabled_env()
        del env["PTILOPSIS_CR_TELEGRAM_CHAT_ID"]
        with self.assertRaises(ValueError) as ctx:
            build_cr_telegram_sink_config_from_env(env)
        self.assertNotIn(FAKE_CHAT_ID, str(ctx.exception))


# ---------------------------------------------------------------------------
# Test Group D — Normal config construction
# ---------------------------------------------------------------------------


class TestNormalConfigConstruction(unittest.TestCase):
    """Group D: basic enabled env produces correct config."""

    def _default_env(self) -> dict[str, str]:
        return {
            "PTILOPSIS_CR_TELEGRAM_SEND": "1",
            "PTILOPSIS_CR_TELEGRAM_BOT_TOKEN": FAKE_TOKEN,
            "PTILOPSIS_CR_TELEGRAM_CHAT_ID": FAKE_CHAT_ID,
        }

    def test_returns_config(self) -> None:
        config = build_cr_telegram_sink_config_from_env(self._default_env())
        self.assertIsNotNone(config)

    def test_bot_token_matches(self) -> None:
        config = build_cr_telegram_sink_config_from_env(self._default_env())
        assert config is not None
        self.assertEqual(config.bot_token, FAKE_TOKEN)

    def test_chat_id_matches(self) -> None:
        config = build_cr_telegram_sink_config_from_env(self._default_env())
        assert config is not None
        self.assertEqual(config.chat_id, FAKE_CHAT_ID)

    def test_api_base_url_uses_default(self) -> None:
        config = build_cr_telegram_sink_config_from_env(self._default_env())
        assert config is not None
        self.assertEqual(config.api_base_url, "https://api.telegram.org")

    def test_timeout_uses_default(self) -> None:
        config = build_cr_telegram_sink_config_from_env(self._default_env())
        assert config is not None
        self.assertEqual(config.timeout_seconds, 10.0)

    def test_parse_mode_is_none(self) -> None:
        config = build_cr_telegram_sink_config_from_env(self._default_env())
        assert config is not None
        self.assertIsNone(config.parse_mode)

    def test_disable_web_page_preview_is_true(self) -> None:
        config = build_cr_telegram_sink_config_from_env(self._default_env())
        assert config is not None
        self.assertTrue(config.disable_web_page_preview)

    def test_config_repr_does_not_contain_token(self) -> None:
        config = build_cr_telegram_sink_config_from_env(self._default_env())
        assert config is not None
        self.assertNotIn(FAKE_TOKEN, repr(config))


# ---------------------------------------------------------------------------
# Test Group E — Optional values
# ---------------------------------------------------------------------------


class TestOptionalValues(unittest.TestCase):
    """Group E: custom optional fields are passed through."""

    def _env(self, **overrides: str) -> dict[str, str]:
        base = {
            "PTILOPSIS_CR_TELEGRAM_SEND": "1",
            "PTILOPSIS_CR_TELEGRAM_BOT_TOKEN": FAKE_TOKEN,
            "PTILOPSIS_CR_TELEGRAM_CHAT_ID": FAKE_CHAT_ID,
        }
        base.update(overrides)
        return base

    def test_custom_api_base_url(self) -> None:
        config = build_cr_telegram_sink_config_from_env(
            self._env(PTILOPSIS_CR_TELEGRAM_API_BASE_URL="https://custom.api")
        )
        assert config is not None
        self.assertEqual(config.api_base_url, "https://custom.api")

    def test_custom_timeout_parsed_as_float(self) -> None:
        config = build_cr_telegram_sink_config_from_env(
            self._env(PTILOPSIS_CR_TELEGRAM_TIMEOUT_SECONDS="25.5")
        )
        assert config is not None
        self.assertEqual(config.timeout_seconds, 25.5)

    def test_parse_mode_passed_through(self) -> None:
        config = build_cr_telegram_sink_config_from_env(
            self._env(PTILOPSIS_CR_TELEGRAM_PARSE_MODE="HTML")
        )
        assert config is not None
        self.assertEqual(config.parse_mode, "HTML")

    def test_disable_preview_true_values(self) -> None:
        for val in ("1", "true", "yes", "on", "True", "YES", "ON"):
            config = build_cr_telegram_sink_config_from_env(
                self._env(PTILOPSIS_CR_TELEGRAM_DISABLE_WEB_PAGE_PREVIEW=val)
            )
            assert config is not None, f"failed for {val!r}"
            self.assertTrue(
                config.disable_web_page_preview, f"failed for {val!r}"
            )

    def test_disable_preview_false_values(self) -> None:
        for val in ("0", "false", "no", "off", "False", "NO", "OFF"):
            config = build_cr_telegram_sink_config_from_env(
                self._env(PTILOPSIS_CR_TELEGRAM_DISABLE_WEB_PAGE_PREVIEW=val)
            )
            assert config is not None, f"failed for {val!r}"
            self.assertFalse(
                config.disable_web_page_preview, f"failed for {val!r}"
            )

    def test_blank_parse_mode_becomes_none(self) -> None:
        config = build_cr_telegram_sink_config_from_env(
            self._env(PTILOPSIS_CR_TELEGRAM_PARSE_MODE="   ")
        )
        assert config is not None
        self.assertIsNone(config.parse_mode)

    def test_whitespace_stripped_from_token(self) -> None:
        config = build_cr_telegram_sink_config_from_env(
            self._env(PTILOPSIS_CR_TELEGRAM_BOT_TOKEN=f"  {FAKE_TOKEN}  ")
        )
        assert config is not None
        self.assertEqual(config.bot_token, FAKE_TOKEN)

    def test_whitespace_stripped_from_chat_id(self) -> None:
        config = build_cr_telegram_sink_config_from_env(
            self._env(PTILOPSIS_CR_TELEGRAM_CHAT_ID=f"  {FAKE_CHAT_ID}  ")
        )
        assert config is not None
        self.assertEqual(config.chat_id, FAKE_CHAT_ID)


# ---------------------------------------------------------------------------
# Test Group F — Invalid optional values
# ---------------------------------------------------------------------------


class TestInvalidOptionalValues(unittest.TestCase):
    """Group F: invalid optional fields raise ValueError."""

    def _env(self, **overrides: str) -> dict[str, str]:
        base = {
            "PTILOPSIS_CR_TELEGRAM_SEND": "1",
            "PTILOPSIS_CR_TELEGRAM_BOT_TOKEN": FAKE_TOKEN,
            "PTILOPSIS_CR_TELEGRAM_CHAT_ID": FAKE_CHAT_ID,
        }
        base.update(overrides)
        return base

    def test_blank_api_base_url_raises(self) -> None:
        with self.assertRaises(ValueError) as ctx:
            build_cr_telegram_sink_config_from_env(
                self._env(PTILOPSIS_CR_TELEGRAM_API_BASE_URL="   ")
            )
        self.assertIn("PTILOPSIS_CR_TELEGRAM_API_BASE_URL", str(ctx.exception))

    def test_non_numeric_timeout_raises(self) -> None:
        with self.assertRaises(ValueError) as ctx:
            build_cr_telegram_sink_config_from_env(
                self._env(PTILOPSIS_CR_TELEGRAM_TIMEOUT_SECONDS="abc")
            )
        self.assertIn("PTILOPSIS_CR_TELEGRAM_TIMEOUT_SECONDS", str(ctx.exception))

    def test_zero_timeout_raises(self) -> None:
        with self.assertRaises(ValueError) as ctx:
            build_cr_telegram_sink_config_from_env(
                self._env(PTILOPSIS_CR_TELEGRAM_TIMEOUT_SECONDS="0")
            )
        self.assertIn("PTILOPSIS_CR_TELEGRAM_TIMEOUT_SECONDS", str(ctx.exception))

    def test_negative_timeout_raises(self) -> None:
        with self.assertRaises(ValueError) as ctx:
            build_cr_telegram_sink_config_from_env(
                self._env(PTILOPSIS_CR_TELEGRAM_TIMEOUT_SECONDS="-5")
            )
        self.assertIn("PTILOPSIS_CR_TELEGRAM_TIMEOUT_SECONDS", str(ctx.exception))

    def test_invalid_preview_bool_raises(self) -> None:
        with self.assertRaises(ValueError) as ctx:
            build_cr_telegram_sink_config_from_env(
                self._env(PTILOPSIS_CR_TELEGRAM_DISABLE_WEB_PAGE_PREVIEW="maybe")
            )
        self.assertIn(
            "PTILOPSIS_CR_TELEGRAM_DISABLE_WEB_PAGE_PREVIEW", str(ctx.exception)
        )

    def test_error_messages_do_not_contain_token_or_chat_id(self) -> None:
        """Error messages for optional fields must not leak secrets."""
        env = self._env(PTILOPSIS_CR_TELEGRAM_TIMEOUT_SECONDS="not-a-number")
        with self.assertRaises(ValueError) as ctx:
            build_cr_telegram_sink_config_from_env(env)
        msg = str(ctx.exception)
        self.assertNotIn(FAKE_TOKEN, msg)
        self.assertNotIn(FAKE_CHAT_ID, msg)


# ---------------------------------------------------------------------------
# Test Group G — Sink construction
# ---------------------------------------------------------------------------


class _FakeHTTPClient:
    """Minimal fake HTTP client with a ``post_json`` stub."""

    def post_json(
        self,
        url: str,
        payload: dict[str, object],
        *,
        timeout_seconds: float,
    ) -> TelegramHTTPResponse:
        return TelegramHTTPResponse(status_code=200, body='{"ok":true}')


class TestSinkConstruction(unittest.TestCase):
    """Group G: sink construction from env."""

    def _env(self) -> dict[str, str]:
        return {
            "PTILOPSIS_CR_TELEGRAM_SEND": "1",
            "PTILOPSIS_CR_TELEGRAM_BOT_TOKEN": FAKE_TOKEN,
            "PTILOPSIS_CR_TELEGRAM_CHAT_ID": FAKE_CHAT_ID,
        }

    def test_enabled_env_returns_sink(self) -> None:
        sink = build_cr_telegram_sink_from_env(self._env())
        self.assertIsInstance(sink, CRTelegramSink)

    def test_sink_config_matches(self) -> None:
        sink = build_cr_telegram_sink_from_env(self._env())
        assert sink is not None
        config = build_cr_telegram_sink_config_from_env(self._env())
        self.assertEqual(sink.config, config)

    def test_fake_http_client_preserved(self) -> None:
        fake = _FakeHTTPClient()
        sink = build_cr_telegram_sink_from_env(self._env(), http_client=fake)
        assert sink is not None
        self.assertIs(sink.http_client, fake)

    def test_disabled_env_returns_none(self) -> None:
        env = {"PTILOPSIS_CR_TELEGRAM_SEND": "0"}
        self.assertIsNone(build_cr_telegram_sink_from_env(env))

    def test_no_post_json_during_construction(self) -> None:
        """Construction must not trigger any network calls."""
        sentinel = object()

        class SpyClient:
            called = False

            def post_json(self, *a: object, **kw: object) -> object:
                SpyClient.called = True
                return sentinel

        build_cr_telegram_sink_from_env(self._env(), http_client=SpyClient())
        self.assertFalse(SpyClient.called)


# ---------------------------------------------------------------------------
# Test Group H — Boundary checks
# ---------------------------------------------------------------------------


class TestBoundaryChecks(unittest.TestCase):
    """Group H: source inspection for forbidden imports."""

    def test_telegram_env_has_no_forbidden_imports(self) -> None:
        """telegram_env.py must not import forbidden modules."""
        from pathlib import Path

        source = Path(__file__).resolve().parent.parent / "trendradar" / "cr" / "telegram_env.py"
        text = source.read_text(encoding="utf-8")
        forbidden = [
            "trendradar.notification",
            "trendradar.storage",
            "trendradar.config",
            "trendradar.ai",
            "AIAnalysisResult",
            "requests",
            "httpx",
            "aiohttp",
            "cooldown",
            "dedupe",
            "alert_state",
        ]
        for token in forbidden:
            self.assertNotIn(
                token, text, f"telegram_env.py must not contain {token!r}"
            )

    def test_main_imports_telegram_env_only_inside_dispatch_mode_gate(self) -> None:
        # PR-CR-A1 wires the env factory into the CR dispatch hook.  The import
        # must stay lazy (inside the dispatch-mode gate) — never at module top
        # level.
        from pathlib import Path

        source = Path(__file__).resolve().parent.parent / "trendradar" / "__main__.py"
        text = source.read_text(encoding="utf-8")
        self.assertIn("build_cr_telegram_sink_from_env", text)
        # The import statement (not comments) must be inside the gate.
        import_pattern = "from trendradar.cr.telegram_env import"
        self.assertIn(import_pattern, text)
        for line in text.splitlines():
            stripped = line.strip()
            if stripped.startswith("from ") and "telegram_env" in stripped:
                self.assertTrue(
                    line.startswith(" "),
                    f"telegram_env import must not be at top level: {line!r}",
                )
        gate_pos = text.index('resolve_cr_dispatch_mode')
        self.assertGreater(text.index(import_pattern), gate_pos)

    def test_runtime_dry_run_does_not_import_telegram_env(self) -> None:
        from pathlib import Path

        source = (
            Path(__file__).resolve().parent.parent
            / "trendradar"
            / "cr"
            / "runtime_dry_run.py"
        )
        text = source.read_text(encoding="utf-8")
        self.assertNotIn("telegram_env", text)


# ---------------------------------------------------------------------------
# Test Group G — Partial config graceful handling
# ---------------------------------------------------------------------------


class TestPartialConfigGraceful(unittest.TestCase):
    """Group G: partial live Telegram config must not crash the runtime.

    When SEND=1 but credentials are missing, the ValueError should be
    catchable so the caller can treat it as no sink (not_configured receipt).
    """

    def test_missing_token_value_error_is_catchable(self) -> None:
        """Caller can catch ValueError and treat as no sink."""
        env = {
            "PTILOPSIS_CR_TELEGRAM_SEND": "1",
            "PTILOPSIS_CR_TELEGRAM_CHAT_ID": FAKE_CHAT_ID,
        }
        sink = None
        try:
            sink = build_cr_telegram_sink_from_env(env)
        except ValueError:
            sink = None
        self.assertIsNone(sink)

    def test_missing_chat_id_value_error_is_catchable(self) -> None:
        """Caller can catch ValueError and treat as no sink."""
        env = {
            "PTILOPSIS_CR_TELEGRAM_SEND": "1",
            "PTILOPSIS_CR_TELEGRAM_BOT_TOKEN": FAKE_TOKEN,
        }
        sink = None
        try:
            sink = build_cr_telegram_sink_from_env(env)
        except ValueError:
            sink = None
        self.assertIsNone(sink)

    def test_partial_config_does_not_return_sink(self) -> None:
        """Partial config never returns a usable sink."""
        env = {
            "PTILOPSIS_CR_TELEGRAM_SEND": "1",
            # Missing both token and chat_id.
        }
        sink = None
        try:
            sink = build_cr_telegram_sink_from_env(env)
        except ValueError:
            sink = None
        self.assertIsNone(sink)


# ---------------------------------------------------------------------------
# Test Group I — Integration: live dispatch end-to-end
# ---------------------------------------------------------------------------


def _live_dispatch_hotlist_stats() -> list[dict]:
    """Hotlist stats with a low rank to reliably produce a dispatch-ready plan."""
    return [
        {
            "word": "AI",
            "titles": [
                {
                    "title": "AI Title",
                    "source_name": "weibo",
                    "source_id": "weibo",
                    "ranks": [1],
                    "count": 10,
                    "first_time": "09:30",
                    "last_time": "12:00",
                    "url": "https://example.com",
                    "mobileUrl": "",
                    "is_new": False,
                    "rank_timeline": [],
                }
            ],
            "count": 1,
            "position": 0,
        }
    ]


class TestLiveDispatchWithFakeHTTPClient(unittest.TestCase):
    """Group I (Test A): runtime_dry_run end-to-end with injected FakeHTTPClient sink.

    Exercises the full live Telegram path without a real network call.  The
    sink is built from a complete env with a _FakeHTTPClient injected via
    http_client=.  Verifies that dispatch executes, the receipt is accepted,
    and cooldown state is written to a temp path.
    """

    def test_live_dispatch_accepted_state_written(self) -> None:
        """Live mode + FakeHTTPClient: dispatch executes, receipt accepted, cooldown state written."""
        from trendradar.cr.artifacts import CRArtifactConfig
        from trendradar.cr.decision import CRDecisionPolicy
        from trendradar.cr.pipeline import CRPipelineConfig
        from trendradar.cr.runtime_dry_run import build_and_write_cr_runtime_dry_run

        full_env = {
            "PTILOPSIS_CR_TELEGRAM_SEND": "1",
            "PTILOPSIS_CR_TELEGRAM_BOT_TOKEN": FAKE_TOKEN,
            "PTILOPSIS_CR_TELEGRAM_CHAT_ID": FAKE_CHAT_ID,
        }
        sink = build_cr_telegram_sink_from_env(full_env, http_client=_FakeHTTPClient())
        self.assertIsNotNone(sink)

        with tempfile.TemporaryDirectory() as tmp:
            state_path = Path(tmp) / "dispatch_state.json"
            result = build_and_write_cr_runtime_dry_run(
                hotlist_stats=_live_dispatch_hotlist_stats(),
                run_label="test-live-a",
                artifact_config=CRArtifactConfig(root_dir=Path(tmp)),
                pipeline_config=CRPipelineConfig(
                    decision=CRDecisionPolicy(alert_threshold=1.0)
                ),
                dispatch_sink=sink,
                dispatch_mode="live",
                dispatch_state_path=str(state_path),
            )

            # Plan must have dispatched with low threshold + non-empty stats.
            self.assertTrue(
                result.dispatch_plan.should_dispatch,
                "expected plan to dispatch with low alert_threshold and non-empty stats",
            )
            # Execution must have been attempted.
            self.assertIsNotNone(result.dispatch_execution)
            self.assertTrue(result.dispatch_execution.attempted)

            # Receipt artifact must contain an accepted entry.
            data = json.loads(
                result.dispatch_receipt_json_paths.dispatch_receipt_latest_path
                .read_text(encoding="utf-8")
            )
            self.assertEqual(data["dispatch_mode"], "live")
            self.assertTrue(data["plan_should_dispatch"])
            self.assertTrue(
                any(r["status"] == "accepted" for r in data["receipts"]),
                f"expected accepted receipt, got: {data['receipts']}",
            )

            # Cooldown state must have been written after accepted dispatch.
            self.assertIsNotNone(result.dispatch_state_save)
            self.assertTrue(result.dispatch_state_save.saved)
            self.assertTrue(state_path.exists())


class TestLivePartialConfigReceipt(unittest.TestCase):
    """Group I (Test B): SEND=1 + missing token → no crash, not_configured receipt.

    Wiring-level check that live mode + partial env → dispatch_sink=None →
    dispatch_receipts.json contains status: not_configured and no exception is
    raised.  Complements TestPartialConfigGraceful (factory layer) by verifying
    the outcome at the artifact layer.
    """

    def test_partial_config_no_crash_not_configured_receipt(self) -> None:
        """SEND=1 + missing token: no crash, dispatch_receipts.json has not_configured."""
        from trendradar.cr.artifacts import CRArtifactConfig
        from trendradar.cr.decision import CRDecisionPolicy
        from trendradar.cr.pipeline import CRPipelineConfig
        from trendradar.cr.runtime_dry_run import build_and_write_cr_runtime_dry_run

        # Partial env: SEND enabled + chat_id, token missing.
        partial_env = {
            "PTILOPSIS_CR_TELEGRAM_SEND": "1",
            "PTILOPSIS_CR_TELEGRAM_CHAT_ID": FAKE_CHAT_ID,
        }

        # Simulate runtime wiring: catch ValueError, fall back to no sink.
        dispatch_sink = None
        try:
            dispatch_sink = build_cr_telegram_sink_from_env(partial_env)
        except ValueError:
            dispatch_sink = None
        self.assertIsNone(dispatch_sink)

        with tempfile.TemporaryDirectory() as tmp:
            # Must not raise — partial config must not crash.
            result = build_and_write_cr_runtime_dry_run(
                hotlist_stats=_live_dispatch_hotlist_stats(),
                run_label="test-live-b",
                artifact_config=CRArtifactConfig(root_dir=Path(tmp)),
                pipeline_config=CRPipelineConfig(
                    decision=CRDecisionPolicy(alert_threshold=1.0)
                ),
                dispatch_mode="live",
                dispatch_sink=dispatch_sink,
            )

            # Plan must have dispatched (low threshold + non-empty stats).
            self.assertTrue(
                result.dispatch_plan.should_dispatch,
                "expected plan to dispatch with low alert_threshold and non-empty stats",
            )

            # Receipt must contain not_configured — live mode with no sink.
            data = json.loads(
                result.dispatch_receipt_json_paths.dispatch_receipt_latest_path
                .read_text(encoding="utf-8")
            )
            self.assertEqual(data["dispatch_mode"], "live")
            self.assertTrue(data["plan_should_dispatch"])
            self.assertTrue(
                any(r["status"] == "not_configured" for r in data["receipts"]),
                f"expected not_configured with no sink in live mode, got: {data['receipts']}",
            )


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    unittest.main()
