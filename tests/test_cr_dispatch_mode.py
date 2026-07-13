# coding=utf-8
"""
Tests for CR-A dispatch mode resolution (PR-CR-A1).

Covers:
  Group A — Mode resolution from env vars
  Group B — Runtime behavior wiring (source-level checks)
  Group C — Source boundary (no legacy push, no independent Telegram path)

No real network calls.  No real tokens.  No environment mutation.
"""

from __future__ import annotations

import ast
import unittest
from pathlib import Path

from trendradar.cr.dispatch_mode import (
    CR_DISPATCH_ARTIFACT,
    CR_DISPATCH_LIVE,
    CR_DISPATCH_OFF,
    CR_DISPATCH_SHADOW,
    resolve_cr_dispatch_mode,
)
from tests.cr_main_ast import (
    assigned_name,
    calls,
    import_from_nodes,
    load_cr_dispatch_hook,
)


# ---------------------------------------------------------------------------
# Test Group A — Mode resolution
# ---------------------------------------------------------------------------


class TestModeResolution(unittest.TestCase):
    """Group A: resolve_cr_dispatch_mode returns the correct mode."""

    def test_env_unset_returns_off(self) -> None:
        self.assertEqual(resolve_cr_dispatch_mode({}), CR_DISPATCH_OFF)

    def test_explicit_off(self) -> None:
        self.assertEqual(
            resolve_cr_dispatch_mode({"PTILOPSIS_CR_DISPATCH_MODE": "off"}),
            CR_DISPATCH_OFF,
        )

    def test_explicit_artifact(self) -> None:
        self.assertEqual(
            resolve_cr_dispatch_mode({"PTILOPSIS_CR_DISPATCH_MODE": "artifact"}),
            CR_DISPATCH_ARTIFACT,
        )

    def test_explicit_shadow(self) -> None:
        self.assertEqual(
            resolve_cr_dispatch_mode({"PTILOPSIS_CR_DISPATCH_MODE": "shadow"}),
            CR_DISPATCH_SHADOW,
        )

    def test_explicit_live(self) -> None:
        self.assertEqual(
            resolve_cr_dispatch_mode({"PTILOPSIS_CR_DISPATCH_MODE": "live"}),
            CR_DISPATCH_LIVE,
        )

    def test_invalid_value_returns_off(self) -> None:
        self.assertEqual(
            resolve_cr_dispatch_mode({"PTILOPSIS_CR_DISPATCH_MODE": "bogus"}),
            CR_DISPATCH_OFF,
        )

    def test_empty_value_returns_off(self) -> None:
        self.assertEqual(
            resolve_cr_dispatch_mode({"PTILOPSIS_CR_DISPATCH_MODE": ""}),
            CR_DISPATCH_OFF,
        )

    def test_whitespace_only_returns_off(self) -> None:
        self.assertEqual(
            resolve_cr_dispatch_mode({"PTILOPSIS_CR_DISPATCH_MODE": "   "}),
            CR_DISPATCH_OFF,
        )

    def test_case_insensitive(self) -> None:
        self.assertEqual(
            resolve_cr_dispatch_mode({"PTILOPSIS_CR_DISPATCH_MODE": "ARTIFACT"}),
            CR_DISPATCH_ARTIFACT,
        )
        self.assertEqual(
            resolve_cr_dispatch_mode({"PTILOPSIS_CR_DISPATCH_MODE": "Live"}),
            CR_DISPATCH_LIVE,
        )

    def test_stripped_value(self) -> None:
        self.assertEqual(
            resolve_cr_dispatch_mode({"PTILOPSIS_CR_DISPATCH_MODE": "  shadow  "}),
            CR_DISPATCH_SHADOW,
        )


# ---------------------------------------------------------------------------
# Test Group A2 — Compatibility alias (PTILOPSIS_CR_DRY_RUN)
# ---------------------------------------------------------------------------


class TestDryRunCompatAlias(unittest.TestCase):
    """Group A2: PTILOPSIS_CR_DRY_RUN=1 maps to artifact."""

    def test_dry_run_one_maps_to_artifact(self) -> None:
        self.assertEqual(
            resolve_cr_dispatch_mode({"PTILOPSIS_CR_DRY_RUN": "1"}),
            CR_DISPATCH_ARTIFACT,
        )

    def test_dry_run_zero_is_ignored(self) -> None:
        self.assertEqual(
            resolve_cr_dispatch_mode({"PTILOPSIS_CR_DRY_RUN": "0"}),
            CR_DISPATCH_OFF,
        )

    def test_dry_run_other_value_is_ignored(self) -> None:
        self.assertEqual(
            resolve_cr_dispatch_mode({"PTILOPSIS_CR_DRY_RUN": "true"}),
            CR_DISPATCH_OFF,
        )

    def test_dry_run_empty_is_ignored(self) -> None:
        self.assertEqual(
            resolve_cr_dispatch_mode({"PTILOPSIS_CR_DRY_RUN": ""}),
            CR_DISPATCH_OFF,
        )


# ---------------------------------------------------------------------------
# Test Group A3 — Precedence
# ---------------------------------------------------------------------------


class TestPrecedence(unittest.TestCase):
    """Group A3: explicit PTILOPSIS_CR_DISPATCH_MODE wins over DRY_RUN."""

    def test_dispatch_mode_wins_over_dry_run(self) -> None:
        self.assertEqual(
            resolve_cr_dispatch_mode({
                "PTILOPSIS_CR_DISPATCH_MODE": "live",
                "PTILOPSIS_CR_DRY_RUN": "1",
            }),
            CR_DISPATCH_LIVE,
        )

    def test_dispatch_mode_off_wins_over_dry_run(self) -> None:
        self.assertEqual(
            resolve_cr_dispatch_mode({
                "PTILOPSIS_CR_DISPATCH_MODE": "off",
                "PTILOPSIS_CR_DRY_RUN": "1",
            }),
            CR_DISPATCH_OFF,
        )

    def test_dispatch_mode_artifact_wins_over_dry_run(self) -> None:
        self.assertEqual(
            resolve_cr_dispatch_mode({
                "PTILOPSIS_CR_DISPATCH_MODE": "artifact",
                "PTILOPSIS_CR_DRY_RUN": "1",
            }),
            CR_DISPATCH_ARTIFACT,
        )

    def test_invalid_dispatch_mode_wins_over_dry_run(self) -> None:
        """Invalid dispatch mode → off, even when DRY_RUN=1 is set."""
        self.assertEqual(
            resolve_cr_dispatch_mode({
                "PTILOPSIS_CR_DISPATCH_MODE": "invalid",
                "PTILOPSIS_CR_DRY_RUN": "1",
            }),
            CR_DISPATCH_OFF,
        )


# ---------------------------------------------------------------------------
# Test Group B — Runtime behavior (source-level)
# ---------------------------------------------------------------------------


PROJECT_ROOT = Path(__file__).resolve().parent.parent
class TestRuntimeBehavior(unittest.TestCase):
    """Group B: AST checks for dispatch mode wiring."""

    def test_main_uses_resolve_cr_dispatch_mode(self) -> None:
        hook = load_cr_dispatch_hook()
        self.assertEqual(len(calls(hook.resolve_assignment, "resolve_cr_dispatch_mode")), 1)

    def test_main_checks_off_mode(self) -> None:
        self.assertIsInstance(load_cr_dispatch_hook().off_gate, ast.If)

    def test_main_checks_live_mode_for_sink(self) -> None:
        self.assertIsInstance(load_cr_dispatch_hook().live_gate, ast.If)

    def test_main_does_not_use_dry_run_as_gate(self) -> None:
        """The old PTILOPSIS_CR_DRY_RUN gate is replaced by dispatch mode."""
        hook = load_cr_dispatch_hook()
        self.assertNotIn(
            "PTILOPSIS_CR_DRY_RUN",
            {
                node.value
                for node in ast.walk(hook.function)
                if isinstance(node, ast.Constant) and isinstance(node.value, str)
            },
        )

    def test_dry_run_still_referenced_in_dispatch_mode_module(self) -> None:
        """dispatch_mode.py references DRY_RUN for compatibility."""
        dm_path = PROJECT_ROOT / "trendradar" / "cr" / "dispatch_mode.py"
        source = dm_path.read_text(encoding="utf-8")
        self.assertIn("PTILOPSIS_CR_DRY_RUN", source)

    def test_artifact_and_shadow_do_not_build_sink(self) -> None:
        """In __main__.py, the sink is only built inside the live check."""
        hook = load_cr_dispatch_hook()
        self.assertEqual(
            calls(hook.tree, "build_cr_telegram_sink_from_env"),
            calls(hook.live_gate, "build_cr_telegram_sink_from_env"),
        )
        self.assertEqual(
            import_from_nodes(hook.tree, "trendradar.cr.telegram_env"),
            import_from_nodes(hook.live_gate, "trendradar.cr.telegram_env"),
        )

    def test_dispatch_sink_default_is_none(self) -> None:
        """_dispatch_sink defaults to None before the live check."""
        hook = load_cr_dispatch_hook()
        live_index = hook.off_gate.body.index(hook.live_gate)
        sink_defaults = [
            index
            for index, statement in enumerate(hook.off_gate.body)
            if assigned_name(statement) == "_dispatch_sink"
            and isinstance(statement, ast.Assign)
            and isinstance(statement.value, ast.Constant)
            and statement.value.value is None
        ]
        self.assertEqual(len(sink_defaults), 1)
        self.assertLess(sink_defaults[0], live_index)


# ---------------------------------------------------------------------------
# Test Group C — Source boundary
# ---------------------------------------------------------------------------


class TestSourceBoundary(unittest.TestCase):
    """Group C: no legacy push or independent Telegram path in dispatch hook."""

    def test_no_legacy_push_tokens_in_dispatch_hook(self) -> None:
        """The dispatch hook region must not reference legacy push."""
        region = ast.unparse(load_cr_dispatch_hook().off_gate)

        forbidden = (
            "_send_notification_if_needed",
            "dispatch_all",
            "send_to_telegram",
            "trendradar.notification",
            "NotificationDispatcher",
        )
        for token in forbidden:
            self.assertNotIn(
                token,
                region,
                f"legacy push token {token!r} in dispatch hook region",
            )

    def test_no_ptilopsis_cr_telegram_send_code_in_main(self) -> None:
        """PTILOPSIS_CR_TELEGRAM_SEND must not be read directly in __main__.py.

        Documentation strings may mention the env var; the runtime must still
        leave this gate inside trendradar.cr.telegram_env.
        """
        tree = load_cr_dispatch_hook().tree
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr == "get"
                and isinstance(node.func.value, ast.Attribute)
                and node.func.value.attr == "environ"
                and isinstance(node.func.value.value, ast.Name)
                and node.func.value.value.id == "os"
                and node.args
                and isinstance(node.args[0], ast.Constant)
                and node.args[0].value == "PTILOPSIS_CR_TELEGRAM_SEND"
            ):
                self.fail("PTILOPSIS_CR_TELEGRAM_SEND read via os.environ.get")
            if (
                isinstance(node, ast.Subscript)
                and isinstance(node.value, ast.Attribute)
                and node.value.attr == "environ"
                and isinstance(node.value.value, ast.Name)
                and node.value.value.id == "os"
                and isinstance(node.slice, ast.Constant)
                and node.slice.value == "PTILOPSIS_CR_TELEGRAM_SEND"
            ):
                self.fail("PTILOPSIS_CR_TELEGRAM_SEND read via os.environ[]")


if __name__ == "__main__":
    unittest.main()
